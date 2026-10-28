"""
Voice cloning service.

Accepts a short uploaded audio sample (ideally 6-30 seconds of clean
speech), validates and prepares it as an XTTS speaker-conditioning
reference clip, then registers it as a new selectable voice.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import AudioProcessingError, ValidationError
from app.core.logging_config import get_logger
from app.models.schemas import CloneVoiceResponse
from app.services.voice_registry import get_voice_registry
from app.utils import audio_processing as audio_utils
from app.utils.file_manager import validate_upload

logger = get_logger(__name__)

MIN_CLIP_SECONDS = 3.0
RECOMMENDED_MAX_SECONDS = 60.0


def clone_voice_from_upload(file_bytes: bytes, filename: str, voice_name: str) -> CloneVoiceResponse:
    settings = get_settings()
    if "xtts" not in settings.ENABLED_ENGINES:
        raise ValidationError("Voice cloning needs the XTTS engine, which is disabled (ENABLED_ENGINES).")
    validate_upload(filename, len(file_bytes))

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_in = Path(tmpdir) / filename
        tmp_in.write_bytes(file_bytes)

        # Convert/standardize to mono 22050Hz WAV, which XTTS speaker
        # conditioning expects, and trim to a sane max length.
        prepared = Path(tmpdir) / "prepared.wav"
        _prepare_reference_clip(tmp_in, prepared)

        duration = audio_utils.get_duration_seconds(prepared)
        if duration < MIN_CLIP_SECONDS:
            raise AudioProcessingError(
                f"Uploaded clip is only {duration:.1f}s; please provide at least "
                f"{MIN_CLIP_SECONDS:.0f}s of clear speech for reliable voice cloning."
            )

        registry = get_voice_registry()
        info = registry.register_cloned_voice(prepared, voice_name)

        return CloneVoiceResponse(
            voice_id=info.voice_id,
            name=info.name,
            message=(
                f"Voice cloned successfully from a {duration:.1f}s reference sample. "
                f"Select voice_id='{info.voice_id}' when generating speech."
            ),
        )


def _prepare_reference_clip(input_path: Path, output_path: Path) -> None:
    """Standardize an uploaded clip to mono 22050Hz WAV, capped at 60s."""
    import subprocess

    audio_utils.ensure_ffmpeg_available()
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-t",
        str(RECOMMENDED_MAX_SECONDS),
        "-ac",
        "1",
        "-ar",
        "22050",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise AudioProcessingError(
                "Failed to process uploaded audio for voice cloning.",
                details={"stderr": result.stderr[-500:]},
            )
    except subprocess.TimeoutExpired as exc:
        raise AudioProcessingError("Audio preparation timed out.") from exc
