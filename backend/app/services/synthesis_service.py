"""
Synthesis service: the full generate pipeline, shared by every engine.

text -> sentence chunks -> engine synthesis per chunk -> punctuation pauses
-> pitch -> speed -> loudness normalization -> wav/mp3 -> SRT subtitles.
"""

from __future__ import annotations

import time
from typing import List

import numpy as np

from app.core.config import get_settings
from app.core.exceptions import EmptyTextError, GenerationError, TextTooLongError
from app.core.logging_config import get_logger
from app.models.schemas import (
    GenerateRequest,
    GenerateResponse,
    SentenceTimestamp,
)
from app.services.engines import get_engine
from app.services.voice_registry import get_voice_registry
from app.utils import audio_processing as audio_utils
from app.utils.file_manager import new_id
from app.utils.subtitle_generator import write_srt
from app.utils.text_processing import prepare_chunks

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

    engine_name, voice = get_voice_registry().resolve(request.voice_id)
    engine = get_engine(engine_name.value)

    chunks = prepare_chunks(request.text)
    if not chunks:
        raise GenerationError("No speakable text remained after normalization.")

    start_time = time.time()
    engine.load()
    synth_start = time.time()

    # --- Synthesis: one engine call per chunk, with a pause after each ---
    segments: List[np.ndarray] = []
    pauses: List[float] = []
    timestamps: List[SentenceTimestamp] = []
    cursor = 0.0
    for chunk in chunks:
        wav = engine.synthesize_chunk(chunk.text, voice, request.language, request.emotion_exaggeration)
        segments.append(wav)
        pause = audio_utils.pause_for_punctuation(chunk.text)
        pauses.append(pause)
        duration = len(wav) / float(engine.sample_rate)
        timestamps.append(
            SentenceTimestamp(
                index=chunk.index, text=chunk.text, start=round(cursor, 3), end=round(cursor + duration, 3)
            )
        )
        cursor += duration + pause
    synth_seconds = time.time() - synth_start

    # Drop the pause after the last chunk so files don't end in dead air.
    audio = audio_utils.concatenate_with_pauses(segments, engine.sample_rate, pauses[:-1])

    job_id = new_id()
    raw_wav_path = settings.OUTPUTS_DIR / f"{job_id}_raw.wav"
    audio_utils.write_wav(raw_wav_path, audio, engine.sample_rate)

    # --- Post-processing: pitch then speed (order matters: pitch via
    # asetrate also perturbs tempo internally but self-corrects, so
    # applying speed afterward gives predictable final tempo) ---
    pitch_path = settings.OUTPUTS_DIR / f"{job_id}_pitch.wav"
    audio_utils.apply_pitch(raw_wav_path, pitch_path, request.pitch_semitones, engine.sample_rate)

    speed_path = settings.OUTPUTS_DIR / f"{job_id}_speed.wav"
    audio_utils.apply_speed(pitch_path, speed_path, request.speed)

    normalized_path = settings.OUTPUTS_DIR / f"{job_id}_norm.wav"
    audio_utils.normalize_loudness(speed_path, normalized_path, engine.sample_rate)

    ext = request.output_format.value
    final_path = settings.OUTPUTS_DIR / f"{job_id}.{ext}"
    audio_utils.convert_format(normalized_path, final_path, ext)

    # Timestamps were measured before the speed change; atempo rescales time by 1/speed.
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
    rtf = round(synth_seconds / cursor, 3) if cursor else 0.0

    logger.info(
        "Generated job=%s engine=%s voice=%s chars=%d chunks=%d duration=%.2fs processing=%.2fs rtf=%.3f",
        job_id, engine_name.value, request.voice_id, len(request.text), len(chunks),
        duration, processing_time, rtf,
    )  # fmt: skip

    return GenerateResponse(
        job_id=job_id,
        voice_id=request.voice_id,
        engine=engine_name,
        language=request.language,
        duration_seconds=round(duration, 2),
        audio_url=f"/api/v1/audio/{job_id}.{ext}",
        srt_url=srt_url,
        format=request.output_format,
        sample_rate=engine.sample_rate,
        sentences=timestamps,
        processing_time_seconds=processing_time,
        real_time_factor=rtf,
    )
