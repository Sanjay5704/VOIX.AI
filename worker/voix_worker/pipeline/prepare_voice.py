"""
Voice preparation (`prepare_voice` jobs).

Takes the user's uploaded clip (ideally 6-30 seconds of clean speech) and
standardises it into an XTTS speaker-conditioning reference: mono 22.05 kHz
WAV, capped at 60 s. Clips shorter than 3 s are rejected permanently.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from voix_worker.audio import audio_processing as audio_utils
from voix_worker.errors import AudioProcessingError, InvalidJobError

MIN_CLIP_SECONDS = 3.0
MAX_CLIP_SECONDS = 60.0
REFERENCE_SAMPLE_RATE = 22_050


def prepare_reference_clip(input_path: Path, output_path: Path) -> float:
    """Standardise `input_path` into `output_path`; returns its duration in seconds."""
    audio_utils.ensure_ffmpeg_available()
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-t", str(MAX_CLIP_SECONDS),
        "-ac", "1", "-ar", str(REFERENCE_SAMPLE_RATE),
        str(output_path),
    ]  # fmt: skip
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise AudioProcessingError("Audio preparation timed out.") from exc
    if result.returncode != 0:
        # Undecodable upload: retrying won't help.
        raise InvalidJobError(
            "Could not decode the uploaded audio for voice cloning.", details={"stderr": result.stderr[-500:]}
        )

    duration = audio_utils.get_duration_seconds(output_path)
    if duration < MIN_CLIP_SECONDS:
        raise InvalidJobError(
            f"Uploaded clip is only {duration:.1f}s; please provide at least "
            f"{MIN_CLIP_SECONDS:.0f}s of clear speech for reliable voice cloning."
        )
    return duration
