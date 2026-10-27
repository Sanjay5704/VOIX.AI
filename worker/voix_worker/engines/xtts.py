"""
Coqui XTTS-v2 engine: multilingual, zero-shot voice cloning.

LICENCE: XTTS-v2 weights are under the Coqui Public Model License
(non-commercial). Coqui has shut down, so no commercial licence can be
bought. VOIX keeps XTTS for cloning demos and defaults to Kokoro.

Design notes:
  * The model is loaded once (lazily, on first job) since loading takes
    several seconds to tens of seconds.
  * Speaker conditioning (GPT latents + speaker embedding) is computed once
    per voice and cached, instead of on every chunk as `TTS.tts(speaker_wav=...)`
    does. Long scripts are dozens of chunks, so this is a large saving.
  * Synthesis stays per-chunk (see audio.text_processing): XTTS degrades past
    ~250 characters per call, and per-chunk output gives subtitle timestamps.
  * `expressiveness` scales the sampling temperature, pushing delivery from
    flat toward more expressive without a separate emotion model.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any

import numpy as np

from voix_worker.engines.base import Engine, VoiceSpec
from voix_worker.engines.device import DeviceInfo, detect_device
from voix_worker.errors import EngineError, InvalidJobError

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24_000
BASE_TEMPERATURE = 0.65  # XTTS default is ~0.65-0.75
LATENT_CACHE_SIZE = 16
LANG_ALIASES = {"en-us": "en", "en-gb": "en", "zh": "zh-cn"}


class XTTSEngine(Engine):
    id = "xtts"
    supports_cloning = True

    def __init__(self, model_name: str, device: str = "auto", use_fp16: bool = False) -> None:
        super().__init__()
        self.model_name = model_name
        self.device_info: DeviceInfo = detect_device(device, use_fp16)
        self._tts: Any = None
        self._load_lock = threading.Lock()
        self._latents: OrderedDict[str, tuple[Any, Any]] = OrderedDict()

    @property
    def sample_rate(self) -> int:
        return SAMPLE_RATE

    @property
    def is_loaded(self) -> bool:
        return self._tts is not None

    @property
    def _model(self) -> Any:
        return self._tts.synthesizer.tts_model

    def load(self) -> None:
        if self._tts is not None:
            return
        with self._load_lock:
            if self._tts is not None:
                return
            os.environ.setdefault("COQUI_TOS_AGREED", "1")  # non-interactive CPML acceptance
            logger.info("Loading XTTS-v2 '%s' on %s ...", self.model_name, self.device_info.device)
            start = time.perf_counter()
            try:
                from TTS.api import TTS

                self._tts = TTS(self.model_name).to(self.device_info.device)
            except Exception as exc:  # noqa: BLE001
                raise EngineError(f"Could not load XTTS model '{self.model_name}': {exc}") from exc
            self.load_ms = int((time.perf_counter() - start) * 1000)
            logger.info("XTTS-v2 loaded in %.1fs", self.load_ms / 1000)

    def unload(self) -> None:
        if self._tts is None:
            return
        import torch

        self._tts = None
        self._latents.clear()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("XTTS-v2 unloaded")

    def _conditioning(self, voice: VoiceSpec) -> tuple[Any, Any]:
        key = str(voice.reference_wav) if voice.reference_wav else f"speaker:{voice.engine_voice_id}"
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
            if voice.engine_voice_id not in speakers:
                raise InvalidJobError(f"XTTS has no built-in speaker '{voice.engine_voice_id}'")
            latents = tuple(speakers[voice.engine_voice_id].values())

        self._latents[key] = latents
        if len(self._latents) > LATENT_CACHE_SIZE:
            self._latents.popitem(last=False)
        return latents

    def synthesize_chunk(
        self, text: str, voice: VoiceSpec, language: str, expressiveness: float = 1.0
    ) -> np.ndarray:
        self.load()
        lang = LANG_ALIASES.get(language.lower(), language.lower())
        gpt_cond_latent, speaker_embedding = self._conditioning(voice)
        temperature = max(0.3, min(1.0, BASE_TEMPERATURE * expressiveness))
        try:
            out = self._model.inference(
                text,
                lang,
                gpt_cond_latent,
                speaker_embedding,
                temperature=temperature,
                enable_text_splitting=False,  # we already chunk
            )
        except Exception as exc:  # noqa: BLE001  (CUDA OOM etc. are worth a retry)
            raise EngineError(f"XTTS inference failed: {exc}") from exc
        wav = out["wav"]
        if hasattr(wav, "cpu"):
            wav = wav.cpu().numpy()
        return np.asarray(wav, dtype=np.float32).reshape(-1)

    def describe(self) -> dict[str, str | None]:
        return {"engine": self.id, "model": self.model_name, "device": self.device_info.device}
