"""Engine interface: every TTS backend turns one text chunk into float32 audio.

Chunking, pauses, pitch/speed, loudness, encoding and subtitles are shared
pipeline code (see pipeline/synthesize.py), so an engine only implements
model-specific inference.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class VoiceSpec:
    """What an engine needs to speak as a voice.

    System voices carry a built-in `engine_voice_id` (Kokoro voicepack, XTTS
    studio speaker); cloned voices carry a local `reference_wav`.
    """

    voice_id: str
    engine_voice_id: str | None = None
    reference_wav: Path | None = None


class Engine(ABC):
    id: str = ""
    supports_cloning: bool = False

    def __init__(self) -> None:
        self.load_ms: int | None = None  # set by load(); reported in job metrics

    @property
    @abstractmethod
    def sample_rate(self) -> int: ...

    @property
    def is_loaded(self) -> bool:
        return True

    def load(self) -> None:  # noqa: B027  (optional hook; mock engines need no weights)
        """Load weights. Must be idempotent; called lazily before first use."""

    def unload(self) -> None:  # noqa: B027
        """Release memory (e.g. on shutdown)."""

    @abstractmethod
    def synthesize_chunk(
        self, text: str, voice: VoiceSpec, language: str, expressiveness: float = 1.0
    ) -> np.ndarray:
        """Return mono float32 audio in [-1, 1] at `sample_rate`."""

    def describe(self) -> dict[str, str | None]:
        return {"engine": self.id}
