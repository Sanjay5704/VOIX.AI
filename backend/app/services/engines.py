"""
TTS engines behind one small interface.

Two engines are supported:

  * **Kokoro-82M** (Apache-2.0): fast and light, fixed built-in voices.
    This is the default.
  * **Coqui XTTS-v2** (Coqui Public Model License, non-commercial): slower,
    but can clone a voice from a short reference clip.

Each engine only turns ONE short chunk of text into audio. Splitting text into
chunks, pauses, pitch/speed, loudness and subtitles are shared code in
`synthesis_service`, so adding a third engine means writing one class.

Models are loaded lazily (on first use, or by the warm-up thread at startup)
and kept in memory as singletons.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from app.core.config import get_settings
from app.core.exceptions import GenerationError, ModelLoadError
from app.core.logging_config import get_logger
from app.services.device_manager import DeviceInfo, detect_device

logger = get_logger(__name__)

SAMPLE_RATE = 24_000  # both engines output 24 kHz audio


@dataclass(frozen=True)
class VoiceRef:
    """How an engine should speak: a built-in speaker name, or a reference clip to clone."""

    speaker: Optional[str] = None
    reference_wav: Optional[Path] = None


class Engine:
    name = ""

    def __init__(self) -> None:
        self.device_info: DeviceInfo = detect_device()
        self.load_seconds: Optional[float] = None
        self._ready = False  # True only after loading AND warm-up have finished
        self._lock = threading.Lock()
        # One synthesis at a time per engine: a laptop GPU has limited VRAM.
        self._busy = threading.Semaphore(get_settings().MAX_CONCURRENT_GENERATIONS)

    @property
    def sample_rate(self) -> int:
        return SAMPLE_RATE

    @property
    def is_loaded(self) -> bool:
        return self._ready

    def load(self) -> None:
        if self.is_loaded:
            return
        with self._lock:
            if self.is_loaded:
                return
            logger.info("Loading %s on %s ...", self.name, self.device_info.device)
            start = time.time()
            try:
                self._load()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to load %s", self.name)
                raise ModelLoadError(f"Could not load the {self.name} model: {exc}") from exc
            self._ready = True
            self.load_seconds = round(time.time() - start, 1)
            logger.info("%s loaded in %.1fs", self.name, self.load_seconds)

    def unload(self) -> None:
        """Free GPU memory."""

    def synthesize_chunk(
        self, text: str, voice: VoiceRef, language: str, expressiveness: float = 1.0
    ) -> np.ndarray:
        """Return mono float32 audio for one short chunk of text."""
        self.load()
        timeout = get_settings().GENERATION_TIMEOUT_SECONDS
        if not self._busy.acquire(timeout=timeout):
            raise GenerationError("Server is busy; timed out waiting for a free generation slot.")
        try:
            return self._synthesize(text, voice, language, expressiveness)
        except (GenerationError, ModelLoadError):
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s synthesis failed", self.name)
            raise GenerationError(f"Speech synthesis failed: {exc}") from exc
        finally:
            self._busy.release()

    # --- engine specific ---
    def _load(self) -> None:
        raise NotImplementedError

    def _synthesize(self, text: str, voice: VoiceRef, language: str, expressiveness: float) -> np.ndarray:
        raise NotImplementedError


class XTTSEngine(Engine):
    """Coqui XTTS-v2: multilingual, zero-shot voice cloning.

    Speed-up over calling `TTS.tts(speaker_wav=...)` per chunk: the speaker
    conditioning (GPT latents + speaker embedding) is computed once per voice
    and cached, instead of being recomputed for every sentence.
    """

    name = "xtts"
    LANG_ALIASES = {"en-us": "en", "en-gb": "en", "zh": "zh-cn"}

    def __init__(self) -> None:
        super().__init__()
        self._tts: Any = None
        self._latents: "OrderedDict[str, tuple]" = OrderedDict()

    @property
    def _model(self) -> Any:
        return self._tts.synthesizer.tts_model

    def _load(self) -> None:
        os.environ.setdefault("COQUI_TOS_AGREED", "1")  # non-interactive licence acceptance
        from TTS.api import TTS

        self._tts = TTS(get_settings().TTS_MODEL_NAME).to(self.device_info.device)

    def unload(self) -> None:
        if self._tts is None:
            return
        self._ready = False
        self._tts = None
        self._latents.clear()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def _conditioning(self, voice: VoiceRef) -> tuple:
        key = str(voice.reference_wav) if voice.reference_wav else f"speaker:{voice.speaker}"
        if key in self._latents:
            self._latents.move_to_end(key)
            return self._latents[key]
        model = self._model
        if voice.reference_wav is not None:
            cfg = model.config
            latents = model.get_conditioning_latents(
                audio_path=[str(voice.reference_wav)],
                gpt_cond_len=cfg.gpt_cond_len,
                gpt_cond_chunk_len=cfg.gpt_cond_chunk_len,
                max_ref_length=cfg.max_ref_len,
                sound_norm_refs=cfg.sound_norm_refs,
            )
        else:
            speakers = model.speaker_manager.speakers if model.speaker_manager else {}
            if voice.speaker not in speakers:
                raise GenerationError(f"XTTS has no built-in speaker '{voice.speaker}'")
            latents = tuple(speakers[voice.speaker].values())
        self._latents[key] = latents
        if len(self._latents) > 16:
            self._latents.popitem(last=False)
        return latents

    def _synthesize(self, text: str, voice: VoiceRef, language: str, expressiveness: float) -> np.ndarray:
        lang = self.LANG_ALIASES.get(language.lower(), language.lower())
        gpt_cond_latent, speaker_embedding = self._conditioning(voice)
        # temperature nudges expressiveness; XTTS default is ~0.65-0.75
        temperature = max(0.3, min(1.0, 0.65 * expressiveness))
        out = self._model.inference(
            text, lang, gpt_cond_latent, speaker_embedding,
            temperature=temperature, enable_text_splitting=False,
        )  # fmt: skip
        wav = out["wav"]
        if hasattr(wav, "cpu"):
            wav = wav.cpu().numpy()
        return np.asarray(wav, dtype=np.float32).reshape(-1)


class KokoroEngine(Engine):
    """Kokoro-82M: small and fast, fixed voices, no cloning.

    The first letter of a voice id picks its language pipeline
    ("a" = American English, "b" = British English).
    """

    name = "kokoro"

    def __init__(self) -> None:
        super().__init__()
        self._model: Any = None
        self._pipelines: Dict[str, Any] = {}

    def _load(self) -> None:
        from kokoro import KModel

        repo = get_settings().KOKORO_REPO_ID
        self._model = KModel(repo_id=repo).to(self.device_info.device).eval()
        # Build the English text-to-phoneme pipelines and run one warm-up call now,
        # so the first real request isn't slowed down by one-time setup.
        for lang in ("a", "b"):
            self._pipeline(lang)
        for _ in self._pipeline("a")("Warm up.", voice="af_heart"):
            pass

    def unload(self) -> None:
        self._ready = False
        self._model = None
        self._pipelines.clear()

    def _pipeline(self, lang_code: str) -> Any:
        if lang_code not in self._pipelines:
            from kokoro import KPipeline

            self._pipelines[lang_code] = KPipeline(
                lang_code=lang_code, repo_id=get_settings().KOKORO_REPO_ID, model=self._model
            )
        return self._pipelines[lang_code]

    def _synthesize(self, text: str, voice: VoiceRef, language: str, expressiveness: float) -> np.ndarray:
        if not voice.speaker:
            raise GenerationError("Kokoro cannot clone voices; pick a built-in Kokoro voice.")
        pieces = [
            np.asarray(r.audio.cpu().numpy() if hasattr(r.audio, "cpu") else r.audio, dtype=np.float32)
            for r in self._pipeline(voice.speaker[0])(text, voice=voice.speaker, speed=1.0)
            if r.audio is not None
        ]
        return np.concatenate(pieces).reshape(-1) if pieces else np.zeros(0, dtype=np.float32)


_ENGINE_CLASSES = {"xtts": XTTSEngine, "kokoro": KokoroEngine}
_engines: Dict[str, Engine] = {}
_engines_lock = threading.Lock()


def get_engine(name: str) -> Engine:
    """Return the (lazily created) engine singleton for `name`."""
    if name not in get_settings().ENABLED_ENGINES:
        raise GenerationError(f"Engine '{name}' is not enabled on this server.")
    with _engines_lock:
        if name not in _engines:
            _engines[name] = _ENGINE_CLASSES[name]()
        return _engines[name]


def loaded_engines() -> Dict[str, Engine]:
    return dict(_engines)
