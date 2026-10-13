import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

_bearer = HTTPBearer(auto_error=False)


def validate_api_access_token(expected: str, provided: str | None) -> bool:
    """Allow local unauthenticated mode; otherwise compare a bearer token safely."""
    if not expected:
        return True
    return provided is not None and secrets.compare_digest(expected, provided)


def require_api_access(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    expected = settings.api_access_token
    provided = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    if not validate_api_access_token(expected, provided):
        raise HTTPException(status_code=401, detail="A valid API bearer token is required", headers={"WWW-Authenticate": "Bearer"})
