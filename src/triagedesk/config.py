from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    database_url: str
    mode: str = "real"
    read_only: bool = False
    github_token: SecretStr = SecretStr("")
    auth_mode: str = "github"
    auth_encryption_key: SecretStr = SecretStr("")
    github_client_id: str = ""
    allow_token_login: bool = True
    session_hours: int = 8
    github_api_version: str = "2026-03-10"
    openai_api_key: SecretStr = SecretStr("")
    ai_model: str = "gpt-4.1-mini"
    ai_confidence_threshold: float = Field(0.85, ge=0.5, le=1)
    ai_batch_size: int = Field(5, ge=1, le=100)
    ai_request_interval: float = Field(1, ge=0, le=60)
    auto_sync_seconds: int = Field(60, ge=30, le=3600)

    def model_post_init(self, __context):
        if self.mode != "real":
            raise ValueError("Only MODE=real is supported")
        if self.auth_mode != "github":
            raise ValueError("Only AUTH_MODE=github is supported")
        if self.auth_mode == "github":
            if len(self.auth_encryption_key.get_secret_value()) < 32:
                raise ValueError("AUTH_ENCRYPTION_KEY must contain at least 32 random characters")
            if self.mode != "real":
                raise ValueError("GitHub authentication requires MODE=real")
        if not 1 <= self.session_hours <= 24:
            raise ValueError("SESSION_HOURS must be between 1 and 24")
        if self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace("postgres://", "postgresql+psycopg://", 1)
        elif self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache
def settings() -> Settings:
    return Settings()
