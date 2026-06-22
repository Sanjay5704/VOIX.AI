"""
Audio processing utilities.

Wraps FFmpeg (via pydub for simple ops, and direct subprocess for
pitch-shifting which pydub doesn't support natively) to provide:
  * Concatenation of per-sentence audio segments with natural inter-sentence
    pauses
  * Speed change (tempo, without altering pitch) via the `atempo` filter
  * Pitch shifting via `rubberband` filter if available, falling back to
    `asetrate` + resample (changes tempo too, so we re-correct tempo after)
  * Format conversion (WAV <-> MP3)
  * Loudness normalization for consistent output levels
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List

import numpy as np
import soundfile as sf

from app.core.exceptions import AudioProcessingError, FFmpegNotFoundError
from app.core.logging_config import get_logger

logger = get_logger(__name__)


def ensure_ffmpeg_available() -> None:
    if shutil.which("ffmpeg") is None:
        raise FFmpegNotFoundError(
            "ffmpeg was not found on PATH. Install it via your OS package "
            "manager (e.g. `apt-get install ffmpeg`) or see the installation "
            "guide in docs/INSTALL.md."
        )


def concatenate_with_pauses(
    segments: List[np.ndarray],
    sample_rate: int,
    pause_durations: List[float],
) -> np.ndarray:
    """
    Concatenate audio segments, inserting a silent gap after each segment.

    pause_durations[i] is the silence (seconds) inserted AFTER segments[i].
    Length of pause_durations may be len(segments) or len(segments)-1; the
    final implicit trailing pause is omitted if not provided.
    """
    if not segments:
        return np.zeros(0, dtype=np.float32)

    pieces: List[np.ndarray] = []
    for i, seg in enumerate(segments):
        pieces.append(seg.astype(np.float32))
        if i < len(pause_durations):
            pause_samples = int(sample_rate * pause_durations[i])
            if pause_samples > 0:
                pieces.append(np.zeros(pause_samples, dtype=np.float32))

    return np.concatenate(pieces)


def pause_for_punctuation(sentence: str) -> float:
    """
    Determine a natural pause length (seconds) to follow a sentence, based
    on its terminal punctuation. This is what keeps cadence human rather
    than a flat run-on of clauses.
    """
    sentence = sentence.strip()
    if not sentence:
        return 0.15
    last_char = sentence[-1]
    if last_char in "!?":
        return 0.45
    if last_char == ".":
        return 0.40
    if last_char in ",;:":
        return 0.20
    return 0.30


def write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    try:
        sf.write(str(path), audio, sample_rate, subtype="PCM_16")
    except Exception as exc:  # noqa: BLE001
        raise AudioProcessingError(f"Failed to write WAV file: {exc}") from exc


def apply_speed(input_path: Path, output_path: Path, speed: float) -> None:
    """Change tempo without altering pitch using ffmpeg's atempo filter."""
    ensure_ffmpeg_available()
    if abs(speed - 1.0) < 1e-3:
        shutil.copy(input_path, output_path)
        return

    # atempo only supports 0.5-2.0 per filter instance; our API already
    # clamps to that range, so a single filter stage suffices.
    speed = max(0.5, min(2.0, speed))
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-filter:a", f"atempo={speed:.3f}",
        "-vn", str(output_path),
    ]
    _run_ffmpeg(cmd, "speed adjustment")


def apply_pitch(input_path: Path, output_path: Path, semitones: float, sample_rate: int) -> None:
    """
    Shift pitch by `semitones` while preserving duration.

    Uses asetrate to shift pitch (which also changes speed), then atempo
    to compensate the speed change back to 1x, then resamples to the
    target sample rate. This avoids a hard dependency on the rubberband
    ffmpeg plugin, which is not always compiled in.
    """
    ensure_ffmpeg_available()
    if abs(semitones) < 1e-3:
        shutil.copy(input_path, output_path)
        return

    factor = 2 ** (semitones / 12.0)
    new_rate = int(sample_rate * factor)
    tempo_correction = 1.0 / factor

    # atempo filter chain must stay within 0.5-2.0 per stage; chain multiple
    # stages if the correction falls outside that range.
    tempo_filters = _build_atempo_chain(tempo_correction)

    filter_chain = f"asetrate={new_rate},aresample={sample_rate}"
    if tempo_filters:
        filter_chain += "," + ",".join(tempo_filters)

    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-filter:a", filter_chain,
        "-vn", str(output_path),
    ]
    _run_ffmpeg(cmd, "pitch adjustment")


def _build_atempo_chain(factor: float) -> List[str]:
    """Decompose an arbitrary tempo factor into a chain of 0.5-2.0 stages."""
    if abs(factor - 1.0) < 1e-3:
        return []
    filters = []
    remaining = factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.4f}")
    return filters


def convert_format(input_path: Path, output_path: Path, fmt: str) -> None:
    """Convert WAV to MP3 (or pass through) using ffmpeg."""
    ensure_ffmpeg_available()
    fmt = fmt.lower()
    if fmt == "wav":
        if input_path != output_path:
            shutil.copy(input_path, output_path)
        return

    if fmt == "mp3":
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-codec:a", "libmp3lame", "-qscale:a", "2",
            str(output_path),
        ]
        _run_ffmpeg(cmd, "MP3 conversion")
        return

    raise AudioProcessingError(f"Unsupported output format: {fmt}")


def normalize_loudness(input_path: Path, output_path: Path) -> None:
    """Apply EBU R128 loudness normalization for consistent playback volume."""
    ensure_ffmpeg_available()
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-filter:a", "loudnorm=I=-16:TP=-1.5:LRA=11",
        str(output_path),
    ]
    _run_ffmpeg(cmd, "loudness normalization")


def get_duration_seconds(path: Path) -> float:
    ensure_ffmpeg_available()
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        return float(result.stdout.strip())
    except Exception as exc:  # noqa: BLE001
        raise AudioProcessingError(f"Failed to read audio duration: {exc}") from exc


def _run_ffmpeg(cmd: List[str], operation: str) -> None:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, check=False
        )
        if result.returncode != 0:
            logger.error("ffmpeg %s failed: %s", operation, result.stderr[-2000:])
            raise AudioProcessingError(
                f"ffmpeg {operation} failed (exit {result.returncode})",
                details={"stderr": result.stderr[-1000:]},
            )
    except subprocess.TimeoutExpired as exc:
        raise AudioProcessingError(f"ffmpeg {operation} timed out") from exc
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError("ffmpeg executable not found on PATH") from exc
