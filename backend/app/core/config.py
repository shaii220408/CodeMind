from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    redis_url: str
    upload_dir: str = "/uploads"
    max_upload_mb: int = 100
    max_archive_mb: int = 500
    max_archive_files: int = 20000
    llm_timeout_seconds: float = 30.0
    rate_limit_ask_per_minute: int = 30
    rate_limit_uploads_per_hour: int = 10
    rate_limit_dependency_per_minute: int = 60
    repository_clone_timeout_seconds: int = 300
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    api_access_token: str = ""
    llm_model: str = "gpt-4o-mini"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("api_access_token")
    @classmethod
    def validate_api_access_token(cls, value: str) -> str:
        if value and len(value) < 32:
            raise ValueError("API_ACCESS_TOKEN must be at least 32 characters when configured")
        return value

settings = Settings()
