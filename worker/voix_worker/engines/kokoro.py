"""
Kokoro-82M engine (Apache-2.0 weights): the commercially usable default.

82M parameters, so it is fast and light (fits next to XTTS on an 8 GB GPU),
but it has fixed voicepacks and cannot clone voices. The first letter of a
voicepack id selects its language pipeline: `a` = American English,
`b` = British English, ...
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import numpy as np

from voix_worker.engines.base import Engine, VoiceSpec
from voix_worker.engines.device import DeviceInfo, detect_device
from voix_worker.errors import EngineError, InvalidJobError

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24_000


class KokoroEngine(Engine):
    id = "kokoro"
    supports_cloning = False

    def __init__(self, repo_id: str, device: str = "auto") -> None:
        super().__init__()
        self.repo_id = repo_id
        self.device_info: DeviceInfo = detect_device(device)
        self._model: Any = None
        self._pipelines: dict[str, Any] = {}
        self._lock = threading.Lock()

    @property
    def sample_rate(self) -> int:
        return SAMPLE_RATE

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            logger.info("Loading Kokoro '%s' on %s ...", self.repo_id, self.device_info.device)
            start = time.perf_counter()
            try:
                from kokoro import KModel

                self._model = KModel(repo_id=self.repo_id).to(self.device_info.device).eval()
            except Exception as exc:  # noqa: BLE001
                raise EngineError(f"Could not load Kokoro model '{self.repo_id}': {exc}") from exc
            self.load_ms = int((time.perf_counter() - start) * 1000)
            logger.info("Kokoro loaded in %.1fs", self.load_ms / 1000)

    def unload(self) -> None:
        self._model = None
        self._pipelines.clear()

    def _pipeline(self, lang_code: str) -> Any:
        # One G2P pipeline per language, all sharing the single loaded model.
        if lang_code not in self._pipelines:
            from kokoro import KPipeline

            self._pipelines[lang_code] = KPipeline(
                lang_code=lang_code, repo_id=self.repo_id, model=self._model
            )
        return self._pipelines[lang_code]

    def synthesize_chunk(
        self, text: str, voice: VoiceSpec, language: str, expressiveness: float = 1.0
    ) -> np.ndarray:
        if not voice.engine_voice_id:
            raise InvalidJobError("Kokoro voices are fixed voicepacks; cloned voices are not supported")
        self.load()
        pipeline = self._pipeline(voice.engine_voice_id[0])
        try:
            pieces = [
                np.asarray(r.audio.cpu().numpy() if hasattr(r.audio, "cpu") else r.audio, dtype=np.float32)
                for r in pipeline(text, voice=voice.engine_voice_id, speed=1.0)
                if r.audio is not None
            ]
        except Exception as exc:  # noqa: BLE001
            raise EngineError(f"Kokoro inference failed: {exc}") from exc
        if not pieces:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(pieces).reshape(-1)

    def describe(self) -> dict[str, str | None]:
        return {"engine": self.id, "model": self.repo_id, "device": self.device_info.device}
