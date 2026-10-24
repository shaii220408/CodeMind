from pydantic import BaseModel, Field
from typing import Any

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    repository_url: str | None = None

class ProjectOut(ProjectCreate):
    id: str
    class Config: from_attributes = True

class AskRequest(BaseModel):
    project_id: str
    question: str = Field(min_length=2)
    top_k: int = Field(default=8, ge=1, le=30)

class Citation(BaseModel):
    file: str
    start_line: int
    end_line: int
    symbol: str

class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    retrieved_sources: list[dict[str, Any]]

class StatusOut(BaseModel):
    project_id: str
    status: str
    error: str | None = None
