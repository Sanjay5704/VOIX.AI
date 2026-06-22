"""
Application configuration.

All runtime settings are sourced from environment variables (with sane
defaults) so the same codebase runs unmodified in local dev, Docker, and
production. See .env.example for the full list of overridable values.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List


def _bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _list_env(name: str, default: List[str]) -> List[str]:
    val = os.getenv(name)
    if not val:
        return default
    return [item.strip() for item in val.split(",") if item.strip()]


class Settings:
    """Centralized application settings."""

    # --- General ---
    APP_NAME: str = os.getenv("APP_NAME", "XTTS Production TTS API")
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = _bool_env("DEBUG", True)

    # --- Server ---
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # --- CORS ---
    CORS_ORIGINS: List[str] = _list_env(
        "CORS_ORIGINS", ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # --- Paths ---
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    VOICES_DIR: Path = Path(os.getenv("VOICES_DIR", str(BASE_DIR / "voices")))
    OUTPUTS_DIR: Path = Path(os.getenv("OUTPUTS_DIR", str(BASE_DIR / "outputs")))
    UPLOADS_DIR: Path = Path(os.getenv("UPLOADS_DIR", str(BASE_DIR / "uploads")))
    LOGS_DIR: Path = Path(os.getenv("LOGS_DIR", str(BASE_DIR / "logs")))
    MODEL_CACHE_DIR: Path = Path(
        os.getenv("MODEL_CACHE_DIR", str(BASE_DIR / "model_cache"))
    )

    # --- TTS Engine ---
    TTS_MODEL_NAME: str = os.getenv(
        "TTS_MODEL_NAME", "tts_models/multilingual/multi-dataset/xtts_v2"
    )
    # "auto" | "cuda" | "cpu"
    DEVICE_PREFERENCE: str = os.getenv("DEVICE_PREFERENCE", "auto")
    USE_FP16: bool = _bool_env("USE_FP16", True)
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "en")

    # Default built-in voice reference clips (used as XTTS speaker conditioning)
    MALE_VOICE_FILE: str = os.getenv("MALE_VOICE_FILE", "male_default.wav")
    FEMALE_VOICE_FILE: str = os.getenv("FEMALE_VOICE_FILE", "female_default.wav")

    # --- Generation limits ---
    MAX_TEXT_LENGTH: int = int(os.getenv("MAX_TEXT_LENGTH", "5000"))
    MAX_BATCH_ITEMS: int = int(os.getenv("MAX_BATCH_ITEMS", "50"))
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "30"))
    GENERATION_TIMEOUT_SECONDS: int = int(os.getenv("GENERATION_TIMEOUT_SECONDS", "300"))

    # --- Audio ---
    OUTPUT_SAMPLE_RATE: int = int(os.getenv("OUTPUT_SAMPLE_RATE", "24000"))
    AUDIO_RETENTION_HOURS: int = int(os.getenv("AUDIO_RETENTION_HOURS", "24"))

    # --- Concurrency ---
    MAX_CONCURRENT_GENERATIONS: int = int(os.getenv("MAX_CONCURRENT_GENERATIONS", "1"))

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_JSON: bool = _bool_env("LOG_JSON", False)

    def ensure_directories(self) -> None:
        for path in (
            self.VOICES_DIR,
            self.OUTPUTS_DIR,
            self.UPLOADS_DIR,
            self.LOGS_DIR,
            self.MODEL_CACHE_DIR,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
