from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1] or any(c.isspace() for c in value):
            raise ValueError("Enter a valid email address")
        return value


class UserOut(BaseModel):
    id: str
    email: str

    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    repository_url: str | None = None


class ProjectOut(ProjectCreate):
    id: str
    repository_branch: str | None = None
    repository_commit_sha: str | None = None
    sync_status: str = "NOT_CONFIGURED"

    class Config:
        from_attributes = True


class AskRequest(BaseModel):
    project_id: str
    question: str = Field(min_length=2)
    top_k: int = Field(default=8, ge=1, le=30)


class RepositorySyncRequest(BaseModel):
    branch: str | None = Field(default=None, min_length=1, max_length=200)


class Citation(BaseModel):
    file: str
    start_line: int
    end_line: int
    symbol: str


class AskResponse(BaseModel):
    answer: str
    answer_mode: Literal["llm", "fallback", "abstention"]
    evidence_sufficient: bool
    citations: list[Citation]
    retrieved_sources: list[dict[str, Any]]


class StatusOut(BaseModel):
    project_id: str
    status: str
    error: str | None = None
    sync_status: str | None = None
    repository_branch: str | None = None
    repository_commit_sha: str | None = None
    index_revision: int = 0
