"""Deterministic tone generator standing in for a real model.

Lets the whole queue -> worker -> storage -> download path run in CI on a
CPU with no model downloads. Duration scales with text length so subtitle
timing behaves like real speech.
"""

from __future__ import annotations

import zlib

import numpy as np

from voix_worker.engines.base import Engine, VoiceSpec

SECONDS_PER_CHAR = 0.055  # ~ 165 wpm


class MockEngine(Engine):
    id = "mock"
    supports_cloning = True

    def __init__(self, sample_rate: int = 24_000) -> None:
        super().__init__()
        self._sample_rate = sample_rate

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def load(self) -> None:
        self.load_ms = 0

    def synthesize_chunk(
        self, text: str, voice: VoiceSpec, language: str, expressiveness: float = 1.0
    ) -> np.ndarray:
        seconds = max(0.2, len(text) * SECONDS_PER_CHAR)
        n = int(seconds * self._sample_rate)
        # Each voice gets its own pitch, stable across runs.
        freq = 220.0 + (zlib.crc32(voice.voice_id.encode()) % 440)
        t = np.arange(n, dtype=np.float32) / self._sample_rate
        tone = 0.3 * np.sin(2 * np.pi * freq * t)
        fade = min(n // 2, int(0.01 * self._sample_rate))
        if fade:
            ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            tone[:fade] *= ramp
            tone[-fade:] *= ramp[::-1]
        return tone.astype(np.float32)
