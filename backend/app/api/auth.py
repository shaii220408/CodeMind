from datetime import datetime

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import User, UserToken
from app.services.security import hash_token

bearer_scheme = HTTPBearer(auto_error=False)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    token = db.scalar(
        select(UserToken).where(
            UserToken.token_hash == hash_token(credentials.credentials),
            UserToken.expires_at > datetime.utcnow(),
        )
    )
    if token is None:
        raise HTTPException(401, "Invalid or expired bearer token", headers={"WWW-Authenticate": "Bearer"})
    user = db.get(User, token.user_id)
    if user is None:
        raise HTTPException(401, "Invalid bearer token", headers={"WWW-Authenticate": "Bearer"})
    return user