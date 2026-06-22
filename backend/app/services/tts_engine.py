"""
TTS engine: wraps Coqui XTTS-v2 (state-of-the-art open-source multilingual,
voice-cloning capable TTS model) behind a clean synthesis API.

Design notes:
  * The model is loaded once (lazy, on first use) and cached as a singleton,
    since loading XTTS-v2 takes several seconds to tens of seconds.
  * Synthesis happens per-sentence (see utils.text_processing) rather than
    on the whole text blob. This (a) gives us per-sentence timestamps for
    subtitles, (b) lets us insert punctuation-aware pauses between
    sentences for natural cadence, and (c) avoids XTTS quality
    degradation/clipping on long inputs.
  * Speed and pitch are applied as a post-process via ffmpeg (see
    utils.audio_processing) rather than only through XTTS's own `speed`
    param, giving independent control over both.
  * `emotion_exaggeration` scales the reference-conditioning temperature
    and speaking-rate variance slightly to push delivery from flat/neutral
    toward more expressive, without a separate emotion-control model.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import List, Optional

import numpy as np

from app.core.config import get_settings
from app.core.exceptions import GenerationError, ModelLoadError
from app.core.logging_config import get_logger
from app.models.schemas import SentenceTimestamp
from app.services.device_manager import DeviceInfo, detect_device
from app.utils.audio_processing import pause_for_punctuation
from app.utils.text_processing import prepare_chunks

logger = get_logger(__name__)

_engine_lock = threading.Lock()
_engine_instance: Optional["XTTSEngine"] = None


class XTTSEngine:
    """Singleton wrapper around the Coqui XTTS-v2 model."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.device_info: DeviceInfo = detect_device()
        self._model = None
        self._load_lock = threading.Lock()
        self._generation_lock = threading.Semaphore(self.settings.MAX_CONCURRENT_GENERATIONS)

    # ---- Lazy model loading -------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            logger.info(
                "Loading XTTS-v2 model '%s' on device=%s ...",
                self.settings.TTS_MODEL_NAME, self.device_info.device,
            )
            start = time.time()
            try:
                from TTS.api import TTS  # Coqui TTS

                model = TTS(self.settings.TTS_MODEL_NAME)
                model.to(self.device_info.device)
                self._model = model
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to load XTTS-v2 model")
                raise ModelLoadError(
                    f"Could not load TTS model '{self.settings.TTS_MODEL_NAME}': {exc}"
                ) from exc

            elapsed = time.time() - start
            logger.info("XTTS-v2 model loaded in %.1fs", elapsed)

    def unload(self) -> None:
        """Free GPU memory, e.g. for graceful shutdown."""
        if self._model is None:
            return
        try:
            import torch
            del self._model
            self._model = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("XTTS-v2 model unloaded")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error unloading model: %s", exc)

    # ---- Synthesis -------------------------------------------------

    def synthesize(
        self,
        text: str,
        speaker_wav: Path,
        language: str = "en",
        emotion_exaggeration: float = 1.0,
    ) -> tuple[np.ndarray, int, List[SentenceTimestamp]]:
        """
        Synthesize `text` conditioned on `speaker_wav`, returning the
        concatenated waveform, its sample rate, and per-sentence timestamps.
        """
        self.load()
        assert self._model is not None

        chunks = prepare_chunks(text)
        if not chunks:
            raise GenerationError("No synthesizable text remained after normalization.")

        sample_rate = getattr(
            getattr(self._model, "synthesizer", None), "output_sample_rate", None
        ) or self.settings.OUTPUT_SAMPLE_RATE

        acquired = self._generation_lock.acquire(timeout=self.settings.GENERATION_TIMEOUT_SECONDS)
        if not acquired:
            raise GenerationError("Server is busy; timed out waiting for a free generation slot.")

        try:
            segments: List[np.ndarray] = []
            pauses: List[float] = []
            timestamps: List[SentenceTimestamp] = []
            cursor = 0.0

            # temperature nudges expressiveness; XTTS default is ~0.65-0.75
            temperature = max(0.3, min(1.0, 0.65 * emotion_exaggeration))

            for chunk in chunks:
                wav = self._model.tts(
                    text=chunk.text,
                    speaker_wav=str(speaker_wav),
                    language=language,
                    temperature=temperature,
                )
                wav_array = np.asarray(wav, dtype=np.float32)
                segments.append(wav_array)

                pause = pause_for_punctuation(chunk.text)
                pauses.append(pause)

                duration = len(wav_array) / float(sample_rate)
                start = cursor
                end = cursor + duration
                timestamps.append(
                    SentenceTimestamp(index=chunk.index, text=chunk.text, start=round(start, 3), end=round(end, 3))
                )
                cursor = end + pause

            from app.utils.audio_processing import concatenate_with_pauses

            full_audio = concatenate_with_pauses(segments, sample_rate, pauses)
            return full_audio, int(sample_rate), timestamps

        except (GenerationError, ModelLoadError):
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Synthesis failed")
            raise GenerationError(f"Speech synthesis failed: {exc}") from exc
        finally:
            self._generation_lock.release()


def get_engine() -> XTTSEngine:
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = XTTSEngine()
    return _engine_instance
