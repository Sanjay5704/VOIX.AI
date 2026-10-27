"""
Synthesis pipeline: text -> per-chunk engine synthesis -> punctuation pauses
-> pitch -> speed -> loudness normalisation -> wav/mp3 -> SRT, plus metrics.

Engine-agnostic: anything implementing `Engine.synthesize_chunk` plugs in.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from voix_worker.audio import audio_processing as audio_utils
from voix_worker.audio.subtitles import SentenceTimestamp, write_srt
from voix_worker.audio.text_processing import prepare_chunks
from voix_worker.engines.base import Engine, VoiceSpec
from voix_worker.errors import InvalidJobError

logger = logging.getLogger(__name__)

# progress share of the synthesis loop; the rest is post-processing
SYNTH_PROGRESS_SHARE = 0.85

ProgressFn = Callable[[float], None]
CheckFn = Callable[[], None]  # raises to abort (cancel / shutdown)


@dataclass
class SynthesisOutput:
    audio_path: Path
    subtitles_path: Path | None
    result: dict[str, Any] = field(default_factory=dict)


def run_synthesis(
    engine: Engine,
    voice: VoiceSpec,
    params: dict[str, Any],
    workdir: Path,
    on_progress: ProgressFn = lambda _p: None,
    check_abort: CheckFn = lambda: None,
) -> SynthesisOutput:
    t0 = time.perf_counter()
    workdir.mkdir(parents=True, exist_ok=True)
    text: str = params.get("text", "")
    language: str = params.get("language") or "en"
    speed = float(params.get("speed", 1.0))
    pitch = float(params.get("pitch_semitones", 0.0))
    expressiveness = float(params.get("expressiveness", 1.0))
    fmt = params.get("output_format", "mp3")
    want_srt = bool(params.get("subtitles", True))
    if fmt not in ("mp3", "wav"):
        raise InvalidJobError(f"Unsupported output format {fmt!r}")

    chunks = prepare_chunks(text)
    if not chunks:
        raise InvalidJobError("No synthesizable text remained after normalization.")

    was_loaded = engine.is_loaded
    engine.load()
    t_loaded = time.perf_counter()
    sample_rate = engine.sample_rate

    segments: list[np.ndarray] = []
    pauses: list[float] = []
    timestamps: list[SentenceTimestamp] = []
    cursor = 0.0
    for i, chunk in enumerate(chunks):
        check_abort()
        wav = engine.synthesize_chunk(chunk.text, voice, language, expressiveness)
        segments.append(wav)
        pause = audio_utils.pause_for_punctuation(chunk.text)
        pauses.append(pause)
        duration = len(wav) / float(sample_rate)
        timestamps.append(
            SentenceTimestamp(chunk.index, chunk.text, round(cursor, 3), round(cursor + duration, 3))
        )
        cursor += duration + pause
        on_progress(SYNTH_PROGRESS_SHARE * (i + 1) / len(chunks))
    t_synth = time.perf_counter()

    check_abort()
    # Drop the trailing pause so the file doesn't end in dead air.
    full_audio = audio_utils.concatenate_with_pauses(segments, sample_rate, pauses[:-1])

    # Post-processing: pitch then speed. Pitch via asetrate also perturbs tempo
    # but self-corrects, so applying speed afterward gives a predictable tempo.
    raw = workdir / "raw.wav"
    pitched = workdir / "pitch.wav"
    sped = workdir / "speed.wav"
    normalized = workdir / "norm.wav"
    final = workdir / f"output.{fmt}"
    audio_utils.write_wav(raw, full_audio, sample_rate)
    audio_utils.apply_pitch(raw, pitched, pitch, sample_rate)
    audio_utils.apply_speed(pitched, sped, speed)
    audio_utils.normalize_loudness(sped, normalized, sample_rate)
    audio_utils.convert_format(normalized, final, fmt)
    on_progress(0.97)

    # Timestamps were measured on the unsped audio; atempo rescales time by 1/speed.
    if abs(speed - 1.0) > 1e-3:
        timestamps = [t.scaled(speed) for t in timestamps]

    srt_path = None
    if want_srt:
        srt_path = write_srt(timestamps, workdir / "subtitles.srt")

    audio_seconds = audio_utils.get_duration_seconds(final)
    t_end = time.perf_counter()
    processing_s = t_end - t0
    synth_s = t_synth - t_loaded

    metrics = {
        "chars": len(text),
        "chunks": len(chunks),
        "model_load_ms": engine.load_ms if not was_loaded else 0,
        "synthesis_ms": int(synth_s * 1000),
        "postprocess_ms": int((t_end - t_synth) * 1000),
        "processing_ms": int(processing_s * 1000),
        # RTF < 1 means faster than real time. Synthesis-only RTF excludes
        # one-off model loading and ffmpeg, so engines compare fairly.
        "rtf": round(processing_s / audio_seconds, 4) if audio_seconds else None,
        "synthesis_rtf": round(synth_s / (cursor or 1e-9), 4),
        **engine.describe(),
    }
    logger.info(
        "synthesized %d chars in %d chunks -> %.2fs audio in %.2fs (rtf %.3f)",
        len(text), len(chunks), audio_seconds, processing_s, metrics["rtf"] or 0,
    )  # fmt: skip
    return SynthesisOutput(
        audio_path=final,
        subtitles_path=srt_path,
        result={
            "format": fmt,
            "duration_seconds": round(audio_seconds, 3),
            "sample_rate": sample_rate,
            "sentences": [t.__dict__ for t in timestamps],
            "metrics": metrics,
        },
    )
