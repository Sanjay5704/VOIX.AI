"""File management helpers: ID generation, retention cleanup, validation."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import FileTooLargeError, UnsupportedAudioFormatError
from app.core.logging_config import get_logger

logger = get_logger(__name__)

ALLOWED_UPLOAD_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def validate_upload(filename: str, size_bytes: int) -> None:
    settings = get_settings()
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise UnsupportedAudioFormatError(
            f"Unsupported audio format '{ext}'. Allowed: "
            f"{', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}"
        )
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if size_bytes > max_bytes:
        raise FileTooLargeError(
            f"Uploaded file is {size_bytes / 1e6:.1f}MB, exceeds the "
            f"{settings.MAX_UPLOAD_MB}MB limit."
        )


def cleanup_old_outputs() -> int:
    """Delete generated output files older than AUDIO_RETENTION_HOURS. Returns count removed."""
    settings = get_settings()
    cutoff = time.time() - settings.AUDIO_RETENTION_HOURS * 3600
    removed = 0
    for path in settings.OUTPUTS_DIR.glob("*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError as exc:
            logger.warning("Failed to remove stale file %s: %s", path, exc)
    if removed:
        logger.info("Cleanup removed %d stale output file(s)", removed)
    return removed
