import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.security import require_api_access, validate_api_access_token


def test_api_token_is_optional_for_local_mode():
    assert validate_api_access_token("", None)
    assert validate_api_access_token("", "anything")


def test_api_token_requires_exact_bearer_secret():
    assert validate_api_access_token("x" * 40, "x" * 40)
    assert not validate_api_access_token("x" * 40, None)
    assert not validate_api_access_token("x" * 40, "x" * 39 + "y")


def test_short_configured_api_token_is_rejected():
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+psycopg://localhost/db", redis_url="redis://localhost", api_access_token="too-short")


def test_api_dependency_accepts_and_rejects_bearer_credentials(monkeypatch):
    monkeypatch.setattr(settings, "api_access_token", "s" * 40)
    require_api_access(HTTPAuthorizationCredentials(scheme="Bearer", credentials="s" * 40))
    with pytest.raises(HTTPException) as error:
        require_api_access(None)
    assert error.value.status_code == 401
