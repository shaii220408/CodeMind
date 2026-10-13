from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    repository_url: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Project name cannot be blank")
        return value

    @field_validator("repository_url")
    @classmethod
    def validate_repository_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        parsed=urlsplit(value.strip())
        allowed_hosts={"github.com","gitlab.com","bitbucket.org"}
        if (
            parsed.scheme!="https" or parsed.hostname not in allowed_hosts
            or parsed.username or parsed.password or parsed.port not in (None,443)
            or not parsed.path.strip("/") or parsed.query or parsed.fragment
            or ".." in parsed.path.split("/")
        ):
            raise ValueError("Repository URL must be a public HTTPS URL on GitHub, GitLab, or Bitbucket")
        return value.strip().rstrip("/")


class ProjectOut(ProjectCreate):
    id: str
    model_config = ConfigDict(from_attributes=True)


class AskRequest(BaseModel):
    project_id: str
    question: str = Field(min_length=2, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=30)

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Question must contain at least two non-whitespace characters")
        return value


class Citation(BaseModel):
    file: str
    start_line: int
    end_line: int
    symbol: str


class RetrievedDependency(BaseModel):
    target: str
    relation_type: str
    source_file: str | None = None


class RetrievedSource(BaseModel):
    id: str
    document_id: str
    file: str
    symbol: str
    start_line: int
    end_line: int
    content: str
    retrieval_score: float
    retrieval_source: str
    dependencies: list[RetrievedDependency] = Field(default_factory=list)


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    retrieved_sources: list[RetrievedSource]


class StatusOut(BaseModel):
    project_id: str
    status: Literal["NOT_STARTED", "QUEUED", "PROCESSING", "COMPLETED", "FAILED"]
    error: str | None = None


class IndexAccepted(BaseModel):
    job_id: str
    task_id: str
    status: Literal["QUEUED"]


class FileOut(BaseModel):
    id: str
    path: str
    language: str
    content_hash: str


class ChunkSymbolOut(BaseModel):
    symbol: str
    symbol_type: str
    start_line: int
    end_line: int


class FileDetailOut(BaseModel):
    id: str
    path: str
    language: str
    content: str
    chunks: list[ChunkSymbolOut]


class DependencyOut(BaseModel):
    source_document_id: str
    source_file: str
    source_symbol: str | None
    target: str
    relation_type: str


class ImpactEntry(BaseModel):
    file: str
    depth: int
    reasons: list[str]


class ImpactOut(BaseModel):
    target: str
    root_files: list[str]
    affected_files: list[ImpactEntry]
    truncated: bool = False


class OverviewOut(BaseModel):
    project_id: str
    file_count: int
    chunk_count: int
    languages: dict[str, int]
