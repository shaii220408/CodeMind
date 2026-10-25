import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import bearer_scheme, current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.models import Project, User, UserToken
from app.schemas.schemas import AuthResponse, Credentials, UserOut
from app.services.audit import audit_event
from app.services.security import hash_password, hash_token, issue_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["authentication"])


def create_session(db: Session, user: User) -> AuthResponse:
    token = issue_token()
    expires_at = datetime.utcnow() + timedelta(days=settings.auth_token_ttl_days)
    db.add(UserToken(user_id=user.id, token_hash=hash_token(token), expires_at=expires_at))
    db.commit()
    return AuthResponse(access_token=token, expires_at=expires_at, user=user)


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(payload: Credentials, db: Session = Depends(get_db)):
    email = payload.email
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "Enter a valid email address")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")

    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.flush()
        # The first account claims pre-authentication demo projects exactly once.
        db.execute(update(Project).where(Project.owner_id.is_(None)).values(owner_id=user.id))
        response = create_session(db, user)
        audit_event("account.registered", user.id)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists")
    return response


@router.post("/login", response_model=AuthResponse)
def login(payload: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    response = create_session(db, user)
    audit_event("account.logged_in", user.id)
    return response


@router.post("/logout", status_code=204)
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    db.execute(
        delete(UserToken).where(
            UserToken.user_id == user.id,
            UserToken.token_hash == hash_token(credentials.credentials),
        )
    )
    db.commit()
    audit_event("account.logged_out", user.id)
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
