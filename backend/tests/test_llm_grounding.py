import sys
import types as pytypes
from app.services import llm


def test_deterministic_fallback_cites_only_supplied_evidence(monkeypatch):
    monkeypatch.setattr(llm.settings,"gemini_api_key","")
    evidence=[{
        "file":"src/Service.py","start_line":12,"end_line":18,
        "symbol":"retry","content":"if attempts < limit: retry()",
    }]

    response=llm.answer("Where is retry implemented?",evidence)

    assert "src/Service.py:12-18" in response.answer
    assert "retry()" in response.answer
    assert response.answer_mode == "fallback"
    assert response.citations == [{"file":"src/Service.py","start_line":12,"end_line":18,"symbol":"retry"}]
    assert "another-file.py" not in response.answer


def test_fallback_reports_insufficient_evidence(monkeypatch):
    monkeypatch.setattr(llm.settings,"gemini_api_key","")

    response = llm.answer("Explain missing code",[])
    assert "insufficient repository evidence" in response.answer
    assert response.answer_mode == "abstention"
    assert response.citations == []


def test_model_citations_must_match_retrieved_path_and_lines(monkeypatch):
    evidence = [{"file":"src/Service.py","start_line":12,"end_line":18,"symbol":"retry","content":"retry()"}]
    monkeypatch.setattr(llm.settings,"gemini_api_key","present")
    monkeypatch.setattr(llm,"_gemini_generate",lambda prompt: "Retry is called here (src/Service.py:13-14). Also see fake.py:2.")

    response = llm.answer("Where is retry?", evidence)

    assert response.answer_mode == "llm"
    assert response.citations == [{"file":"src/Service.py","start_line":13,"end_line":14,"symbol":"retry"}]
    assert "fake.py" not in str(response.citations)
    assert "fake.py:2" not in response.answer
    assert "could not be verified" in response.answer


def test_model_answer_without_valid_citation_abstains(monkeypatch):
    monkeypatch.setattr(llm.settings,"gemini_api_key","present")
    monkeypatch.setattr(llm,"_gemini_generate",lambda prompt: "It does something.")
    evidence = [{"file":"src/a.py","start_line":1,"end_line":2,"symbol":"a","content":"def a(): pass"}]

    result = llm.answer("What does a do?", evidence)

    assert result.answer_mode == "abstention"
    assert result.citations == []


def test_gemini_provider_errors_are_not_converted_to_fallback(monkeypatch):
    monkeypatch.setattr(llm.settings,"gemini_api_key","present")
    def fail(_prompt): raise llm.GeminiProviderError(503, "Gemini is temporarily unavailable. Retry later.")
    monkeypatch.setattr(llm,"_gemini_generate",fail)
    evidence = [{"file":"src/a.py","start_line":1,"end_line":2,"symbol":"a","content":"def a(): pass"}]

    import pytest
    with pytest.raises(llm.GeminiProviderError,match="temporarily unavailable"):
        llm.answer("What does a do?", evidence)


def test_official_gemini_sdk_request_uses_server_key_model_and_grounded_prompt(monkeypatch):
    calls = {}
    class FakeResponse:
        text = "Grounded answer (src/a.py:1-2)."
    class FakeModels:
        def generate_content(self, **kwargs):
            calls["request"] = kwargs
            return FakeResponse()
    class FakeClient:
        models = FakeModels()
    def create_client(**kwargs):
        calls["client"] = kwargs
        return FakeClient()
    fake_types = pytypes.SimpleNamespace(
        HttpRetryOptions=lambda **kwargs: kwargs,
        HttpOptions=lambda **kwargs: kwargs,
        GenerateContentConfig=lambda **kwargs: kwargs,
    )
    fake_errors = pytypes.SimpleNamespace(APIError=type("APIError", (Exception,), {}))
    fake_genai = pytypes.ModuleType("google.genai")
    fake_genai.Client = create_client
    fake_genai.errors = fake_errors
    fake_genai.types = fake_types
    fake_google = pytypes.ModuleType("google")
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setattr(llm.settings,"gemini_api_key","test-key-value")
    monkeypatch.setattr(llm.settings,"gemini_model","gemini-test-model")
    monkeypatch.setattr(llm.settings,"gemini_timeout_ms",17000)

    generated = llm._gemini_generate("question and repository evidence")

    assert generated == "Grounded answer (src/a.py:1-2)."
    assert calls["client"]["api_key"] == "test-key-value"
    assert calls["client"]["http_options"]["timeout"] == 17000
    assert calls["request"]["model"] == "gemini-test-model"
    assert calls["request"]["contents"] == "question and repository evidence"
    assert calls["request"]["config"]["temperature"] == 0
    assert "untrusted data" in calls["request"]["config"]["system_instruction"]
