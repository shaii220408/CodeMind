import re

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    upload_dir: str = "/uploads"
    max_upload_mb: int = 100
    max_archive_files: int = 10000
    auth_token_ttl_days: int = 30
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_timeout_seconds: int = 30
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("gemini_api_key")
    @classmethod
    def normalize_gemini_api_key(cls, value: str) -> str:
        return value.strip()

    @field_validator("gemini_model")
    @classmethod
    def validate_gemini_model(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise ValueError("GEMINI_MODEL must be a model identifier such as gemini-3.8-flash")
        return value

    @field_validator("gemini_timeout_seconds")
    @classmethod
    def validate_gemini_timeout_seconds(cls, value: int) -> int:
        if not 5 <= value <= 120:
            raise ValueError("GEMINI_TIMEOUT_SECONDS must be between 5 and 120")
        return value

settings = Settings()
