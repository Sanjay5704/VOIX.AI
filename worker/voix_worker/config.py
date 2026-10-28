"""Worker settings (env vars or `worker/.env`)."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_url: str = "http://localhost:8000"
    worker_token: SecretStr = SecretStr("dev-insecure-worker-token")
    worker_name: str = socket.gethostname()

    # Comma-separated in env: ENGINES=kokoro,xtts  (or ENGINES=mock for CPU-only runs)
    engines: Annotated[list[str], NoDecode] = ["kokoro", "xtts"]
    device: Literal["auto", "cuda", "cpu"] = "auto"
    # per-engine: one claim loop per engine (no head-of-line blocking); shared: one loop for all
    lanes: Literal["per-engine", "shared"] = "per-engine"
    use_fp16: bool = False

    cache_dir: Path = Path("cache")
    poll_wait_seconds: float = 10.0  # server-side long-poll per claim request
    heartbeat_interval_seconds: float = 15.0  # must be well under the API's LEASE_SECONDS
    request_timeout_seconds: float = 60.0
    max_retries: int = 5

    xtts_model_name: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    kokoro_repo_id: str = "hexgrad/Kokoro-82M"

    @field_validator("engines", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [e.strip() for e in v.split(",") if e.strip()]
        return v
