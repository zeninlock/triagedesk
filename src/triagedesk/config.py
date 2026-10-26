from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://triagedesk:triagedesk@localhost:5432/triagedesk"
    artifact_dir: Path = Path("artifacts")
    mode: str = "fixture"
    read_only: bool = True
    reviewer_token: SecretStr = SecretStr("")
    reviewer_name: str = "maintainer"
    github_token: SecretStr = SecretStr("")
    auth_mode: str = "local"
    auth_encryption_key: SecretStr = SecretStr("")
    github_client_id: str = ""
    allow_token_login: bool = True
    session_hours: int = 8
    github_api_version: str = "2026-03-10"
    api_url: str = "http://localhost:8000"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_revision: str = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"

    def model_post_init(self, __context):
        if self.mode not in {"fixture", "real"}:
            raise ValueError("MODE must be fixture or real")
        if self.auth_mode not in {"local", "github"}:
            raise ValueError("AUTH_MODE must be local or github")
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
