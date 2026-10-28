"""Control-plane settings, loaded from environment variables (and `.env`)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_DEV_JWT_SECRET = "dev-insecure-jwt-secret-change-me"
_DEV_WORKER_TOKEN = "dev-insecure-worker-token"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["dev", "test", "production"] = "dev"
    app_name: str = "VOIX API"

    # --- Database ---
    database_url: str = "sqlite:///./data/voix.sqlite3"

    # --- Auth ---
    jwt_secret: SecretStr = SecretStr(_DEV_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 60 * 24
    worker_token: SecretStr = SecretStr(_DEV_WORKER_TOKEN)

    # --- Storage ---
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_dir: Path = Path("data/storage")
    s3_bucket: str = ""
    s3_endpoint_url: str | None = None  # e.g. https://<account>.r2.cloudflarestorage.com
    s3_region: str = "auto"
    s3_access_key_id: str = ""
    s3_secret_access_key: SecretStr = SecretStr("")
    s3_presign_ttl_seconds: int = 300

    # --- HTTP ---
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    # --- Engines ---
    # Engines whose system voices are seeded and which jobs may target.
    enabled_engines: Annotated[list[str], NoDecode] = ["kokoro", "xtts"]
    # Engine used for user-cloned voices (must support reference-audio cloning).
    clone_engine: str = "xtts"

    # --- Queue ---
    lease_seconds: int = 60
    default_max_attempts: int = 3
    retry_backoff_seconds: int = 5
    claim_max_wait_seconds: int = 20
    worker_online_seconds: int = 30

    # --- Limits ---
    plan_quotas: dict[str, int] = {"free": 20_000, "pro": 500_000}
    plan_priorities: dict[str, int] = {"free": 0, "pro": 10}
    rate_limit_jobs_per_minute: int = 10
    max_text_chars: int = 5_000
    max_upload_mb: int = 20

    # --- Observability ---
    log_format: Literal["json", "text"] = "json"
    log_level: str = "INFO"
    metrics_token: SecretStr | None = None  # if set, /metrics requires "Authorization: Bearer <token>"

    @model_validator(mode="before")
    @classmethod
    def _split_csv_lists(cls, data: dict) -> dict:
        for key in ("cors_origins", "enabled_engines"):
            for k in (key, key.upper()):
                value = data.get(k)
                if isinstance(value, str):
                    data[k] = [v.strip() for v in value.split(",") if v.strip()]
        return data

    @model_validator(mode="after")
    def _normalise_database_url(self) -> Settings:
        # Hosted Postgres (Neon, Render, Heroku-style) hands out postgres:// URLs;
        # SQLAlchemy needs the driver spelled out.
        for prefix in ("postgres://", "postgresql://"):
            if self.database_url.startswith(prefix):
                self.database_url = "postgresql+psycopg://" + self.database_url[len(prefix) :]
        return self

    @model_validator(mode="after")
    def _refuse_dev_secrets_in_production(self) -> Settings:
        if self.environment == "production":
            if self.jwt_secret.get_secret_value() == _DEV_JWT_SECRET:
                raise ValueError("JWT_SECRET must be set in production")
            if self.worker_token.get_secret_value() == _DEV_WORKER_TOKEN:
                raise ValueError("WORKER_TOKEN must be set in production")
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
