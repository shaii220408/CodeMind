from datetime import datetime, timedelta
from types import SimpleNamespace
import uuid

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.services import llm
from app.services.llm import (
    AnswerResult,
    GeminiAPIError,
    GeminiConnectionError,
    GeminiTimeoutError,
    INSUFFICIENT_EVIDENCE,
    answer,
)


def source(score=0.8, path="src/main.py", start=5, end=8, content="def main(): pass"):
    return {"id": "chunk-1", "retrieval_score": score, "file": path, "start_line": start, "end_line": end, "symbol": "main", "content": content}


def test_answer_abstains_without_evidence(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert answer("What does this project do?", []) == AnswerResult(INSUFFICIENT_EVIDENCE, "abstention", False)


def test_answer_abstains_below_relevance_threshold(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert answer("What does this project do?", [source(score=0.05)]) .mode == "abstention"


def test_answer_abstains_on_weak_semantic_match(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    weak = source(score=0.371, path="src/NotificationService.java", start=1, end=4, content="send notification")
    result = answer("Which orbital launch provider does this project use?", [weak])
    assert result == AnswerResult(INSUFFICIENT_EVIDENCE, "abstention", False)



def test_abstention_does_not_call_gemini_even_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-secret")
    class UnexpectedClient:
        def __init__(self, **kwargs):
            raise AssertionError("provider should not be called for weak evidence")
    monkeypatch.setattr(llm.genai, "Client", UnexpectedClient)
    result = answer("Unrelated?", [source(score=0.2)])
    assert result == AnswerResult(INSUFFICIENT_EVIDENCE, "abstention", False)


def test_fallback_is_marked_and_contains_real_source(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    result = answer("Where is main?", [source()])
    assert result.mode == "fallback" and result.evidence_sufficient
    assert "src/main.py (5-8)" in result.answer
    assert "def main(): pass" in result.answer
    assert "GEMINI_API_KEY" in result.answer


def test_gemini_request_uses_generate_content_and_grounded_evidence(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-secret")
    monkeypatch.setattr(settings, "gemini_model", "gemini-test-flash")
    captured = {}

    class Response:
        text = "The method is in src/main.py:5-8."
    class Models:
        def generate_content(self, **kwargs):
            captured["request"] = kwargs
            return Response()
    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.models = Models()
        def close(self): captured["closed"] = True

    monkeypatch.setattr(llm.genai, "Client", Client)
    result = answer("Where is main?", [source()], conversation=[{"question": "Where is auth?", "answer": "src/auth.py contains it."}])
    assert result == AnswerResult("The method is in src/main.py:5-8.", "llm", True)
    assert captured["client"]["api_key"] == "test-secret"
    assert captured["client"]["http_options"].timeout == settings.gemini_timeout_seconds * 1000
    request = captured["request"]
    assert request["model"] == "gemini-test-flash"
    assert request["config"].system_instruction
    assert request["config"].temperature is None
    prompt = request["contents"]
    assert "Where is main?" in prompt and "SOURCE: src/main.py:5-8" in prompt and "def main(): pass" in prompt
    assert "Where is auth?" in prompt and "src/auth.py contains it." in prompt
    assert captured["closed"] is True


def test_gemini_rejects_citation_outside_retrieved_locations(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-secret")
    class Response:
        text = "Found in src/other.py:99."
    class Models:
        def generate_content(self, **kwargs): return Response()
    class Client:
        def __init__(self, **kwargs): self.models = Models()
        def close(self): pass
    monkeypatch.setattr(llm.genai, "Client", Client)
    assert answer("Where?", [source()]) == AnswerResult(INSUFFICIENT_EVIDENCE, "abstention", False)


def test_gemini_timeout_is_propagated_not_fallback(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-secret")
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/test")
    class Models:
        def generate_content(self, **kwargs): raise httpx.ReadTimeout("timeout", request=request)
    class Client:
        def __init__(self, **kwargs): self.models = Models()
        def close(self): pass
    monkeypatch.setattr(llm.genai, "Client", Client)
    with pytest.raises(GeminiTimeoutError):
        answer("Where?", [source()])


def test_gemini_provider_status_error_is_not_fallback(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-secret")
    class ProviderError(Exception):
        code = 429
    class Models:
        def generate_content(self, **kwargs): raise ProviderError("provider body must not leak")
    class Client:
        def __init__(self, **kwargs): self.models = Models()
        def close(self): pass
    monkeypatch.setattr(llm.genai, "Client", Client)
    with pytest.raises(GeminiAPIError) as error:
        answer("Where?", [source()])
    assert error.value.status_code == 429
    assert "provider body must not leak" not in str(error.value)


def test_transient_gemini_503_retries_once_with_backoff(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-secret")
    attempts = []
    delays = []

    class ProviderError(Exception):
        code = 503

    class Response:
        text = "The method is in src/main.py:5-8."

    class Models:
        def generate_content(self, **kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1:
                raise ProviderError("provider body must not leak")
            return Response()

    class Client:
        def __init__(self, **kwargs): self.models = Models()
        def close(self): pass

    monkeypatch.setattr(llm.genai, "Client", Client)
    monkeypatch.setattr(llm.time, "sleep", delays.append)
    result = answer("Where is main?", [source()])
    assert result.mode == "llm"
    assert len(attempts) == 2
    assert delays == [0.5]


def test_gemini_429_and_504_are_not_retried(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-secret")
    for status in (429, 504):
        calls = []
        class ProviderError(Exception):
            code = status
        class Models:
            def generate_content(self, **kwargs):
                calls.append(kwargs)
                raise ProviderError("provider body must not leak")
        class Client:
            def __init__(self, **kwargs): self.models = Models()
            def close(self): pass
        monkeypatch.setattr(llm.genai, "Client", Client)
        with pytest.raises(GeminiAPIError) as error:
            answer("Where is main?", [source()])
        assert error.value.status_code == status
        assert len(calls) == 1


def test_gemini_configuration_validation():
    with pytest.raises(ValidationError, match="GEMINI_MODEL"):
        Settings(database_url="postgresql://localhost/test", redis_url="redis://localhost", gemini_model="bad/model")
    with pytest.raises(ValidationError, match="GEMINI_MODEL"):
        Settings(database_url="postgresql://localhost/test", redis_url="redis://localhost", gemini_model="  ")
    with pytest.raises(ValidationError, match="GEMINI_TIMEOUT_SECONDS"):
        Settings(database_url="postgresql://localhost/test", redis_url="redis://localhost", gemini_timeout_seconds=4)


def test_gemini_provider_errors_map_to_explicit_service_errors():
    from app.api.routes import llm_provider_http_error
    assert llm_provider_http_error(GeminiTimeoutError()).status_code == 504
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/test")
    assert llm_provider_http_error(GeminiConnectionError()).status_code == 503
    assert llm_provider_http_error(GeminiAPIError(401)).status_code == 502
    assert "GEMINI_API_KEY" in llm_provider_http_error(GeminiAPIError(403)).detail
    assert llm_provider_http_error(GeminiAPIError(429)).status_code == 503
    assert llm_provider_http_error(GeminiAPIError(504)).status_code == 504
    assert llm_provider_http_error(GeminiAPIError(503)).status_code == 503
    assert llm_provider_http_error(GeminiAPIError(404)).status_code == 502


def test_ask_response_persists_mode_and_verified_citations(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import delete
    from app.api import routes
    from app.db.session import SessionLocal
    from app.main import app
    from app.models.models import Project, User, UserToken
    from app.services.security import hash_token, issue_token

    db = SessionLocal()
    user = User(email=f"gemini-{uuid.uuid4().hex}@example.test", password_hash="unused")
    db.add(user); db.flush()
    project = Project(owner_id=user.id, name="gemini-history-test")
    db.add(project); db.flush()
    token = issue_token()
    db.add(UserToken(user_id=user.id, token_hash=hash_token(token), expires_at=datetime.utcnow() + timedelta(days=1)))
    user_id, project_id = user.id, project.id
    db.commit(); db.close()
    evidence = [source()]
    monkeypatch.setattr(routes, "retrieve", lambda *args: evidence)
    monkeypatch.setattr(routes, "answer", lambda *args: AnswerResult("Grounded response.", "llm", True))
    try:
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            response = client.post("/api/ask", headers=headers, json={"project_id": project_id, "question": "Where is main?"})
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["answer_mode"] == "llm"
            assert body["citations"] == [{"file": "src/main.py", "start_line": 5, "end_line": 8, "symbol": "main"}]
            history = client.get(f"/api/projects/{project_id}/history", headers=headers)
            assert history.status_code == 200
            assert history.json()[0]["answer_mode"] == "llm"
            assert history.json()[0]["citations"] == body["citations"]
            assert history.json()[0]["retrieved_sources"][0]["content"] == evidence[0]["content"]
    finally:
        cleanup = SessionLocal()
        cleanup.execute(delete(Project).where(Project.id == project_id))
        cleanup.execute(delete(UserToken).where(UserToken.user_id == user_id))
        cleanup.execute(delete(User).where(User.id == user_id))
        cleanup.commit(); cleanup.close()
