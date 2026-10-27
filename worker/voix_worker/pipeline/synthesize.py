"""
Synthesis service: orchestrates the full generate pipeline —
text -> XTTS synthesis -> speed/pitch post-processing -> format conversion
-> SRT generation -> response assembly.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import List

from app.core.config import get_settings
from app.core.exceptions import EmptyTextError, TextTooLongError
from app.core.logging_config import get_logger
from app.models.schemas import (
    AudioFormat,
    GenerateRequest,
    GenerateResponse,
    SentenceTimestamp,
)
from app.services.tts_engine import get_engine
from app.services.voice_registry import get_voice_registry
from app.utils import audio_processing as audio_utils
from app.utils.file_manager import new_id
from app.utils.subtitle_generator import write_srt

logger = get_logger(__name__)


def validate_text(text: str) -> None:
    settings = get_settings()
    if not text or not text.strip():
        raise EmptyTextError("Text must not be empty.")
    if len(text) > settings.MAX_TEXT_LENGTH:
        raise TextTooLongError(
            f"Text length {len(text)} exceeds the maximum of {settings.MAX_TEXT_LENGTH} characters."
        )


def generate_speech(request: GenerateRequest) -> GenerateResponse:
    """Run the full text-to-speech pipeline for a single request."""
    settings = get_settings()
    validate_text(request.text)

    registry = get_voice_registry()
    speaker_wav = registry.reference_clip_path(request.voice_id)

    engine = get_engine()

    start_time = time.time()
    audio, sample_rate, timestamps = engine.synthesize(
        text=request.text,
        speaker_wav=speaker_wav,
        language=request.language,
        emotion_exaggeration=request.emotion_exaggeration,
    )

    job_id = new_id()
    raw_wav_path = settings.OUTPUTS_DIR / f"{job_id}_raw.wav"
    audio_utils.write_wav(raw_wav_path, audio, sample_rate)

    # --- Post-processing: pitch then speed (order matters: pitch via
    # asetrate also perturbs tempo internally but self-corrects, so
    # applying speed afterward gives predictable final tempo) ---
    pitch_path = settings.OUTPUTS_DIR / f"{job_id}_pitch.wav"
    audio_utils.apply_pitch(raw_wav_path, pitch_path, request.pitch_semitones, sample_rate)

    speed_path = settings.OUTPUTS_DIR / f"{job_id}_speed.wav"
    audio_utils.apply_speed(pitch_path, speed_path, request.speed)

    normalized_path = settings.OUTPUTS_DIR / f"{job_id}_norm.wav"
    audio_utils.normalize_loudness(speed_path, normalized_path)

    ext = request.output_format.value
    final_path = settings.OUTPUTS_DIR / f"{job_id}.{ext}"
    audio_utils.convert_format(normalized_path, final_path, ext)

    # Rescale timestamps to reflect the final speed adjustment
    if abs(request.speed - 1.0) > 1e-3:
        timestamps = [
            SentenceTimestamp(
                index=t.index,
                text=t.text,
                start=round(t.start / request.speed, 3),
                end=round(t.end / request.speed, 3),
            )
            for t in timestamps
        ]

    duration = audio_utils.get_duration_seconds(final_path)

    srt_url = None
    if request.generate_subtitles and timestamps:
        srt_path = settings.OUTPUTS_DIR / f"{job_id}.srt"
        write_srt(timestamps, srt_path)
        srt_url = f"/api/v1/audio/{job_id}.srt"

    # Clean up intermediate files, keep only the final artifact(s)
    for tmp in (raw_wav_path, pitch_path, speed_path, normalized_path):
        try:
            if tmp.exists() and tmp != final_path:
                tmp.unlink()
        except OSError:
            pass

    processing_time = round(time.time() - start_time, 2)

    logger.info(
        "Generated speech job=%s voice=%s lang=%s chars=%d duration=%.2fs processing=%.2fs",
        job_id, request.voice_id, request.language, len(request.text), duration, processing_time,
    )

    return GenerateResponse(
        job_id=job_id,
        voice_id=request.voice_id,
        language=request.language,
        duration_seconds=round(duration, 2),
        audio_url=f"/api/v1/audio/{job_id}.{ext}",
        srt_url=srt_url,
        format=request.output_format,
        sample_rate=settings.OUTPUT_SAMPLE_RATE,
        sentences=timestamps,
        processing_time_seconds=processing_time,
    )
