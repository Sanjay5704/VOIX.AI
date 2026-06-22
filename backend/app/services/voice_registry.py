"""
Voice registry.

Manages the built-in Male/Female preset voices (reference WAV clips used
for XTTS speaker-conditioning) plus any user-cloned voices uploaded at
runtime. Cloned voices are persisted as reference clips under VOICES_DIR
so they survive process restarts.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import get_settings
from app.core.exceptions import VoiceNotFoundError
from app.core.logging_config import get_logger
from app.models.schemas import VoiceGender, VoiceInfo
from app.utils.file_manager import new_id

logger = get_logger(__name__)

_REGISTRY_FILE = "voice_registry.json"


class VoiceRegistry:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._registry_path = self.settings.VOICES_DIR / _REGISTRY_FILE
        self._custom_voices: Dict[str, VoiceInfo] = {}
        self._load_custom_voices()

    # ---- Built-in presets -------------------------------------------------

    def _builtin_voices(self) -> Dict[str, VoiceInfo]:
        return {
            "male": VoiceInfo(
                voice_id="male",
                name="Male Voice",
                gender=VoiceGender.MALE,
                description="Default natural-sounding male narrator voice.",
                is_custom=False,
            ),
            "female": VoiceInfo(
                voice_id="female",
                name="Female Voice",
                gender=VoiceGender.FEMALE,
                description="Default natural-sounding female narrator voice.",
                is_custom=False,
            ),
        }

    def reference_clip_path(self, voice_id: str) -> Path:
        """Resolve a voice_id to its reference audio clip path used for XTTS conditioning."""
        if voice_id == "male":
            return self.settings.VOICES_DIR / self.settings.MALE_VOICE_FILE
        if voice_id == "female":
            return self.settings.VOICES_DIR / self.settings.FEMALE_VOICE_FILE

        info = self._custom_voices.get(voice_id)
        if info is None:
            raise VoiceNotFoundError(f"Voice '{voice_id}' was not found.")
        path = self.settings.VOICES_DIR / "custom" / f"{voice_id}.wav"
        if not path.exists():
            raise VoiceNotFoundError(f"Reference clip for voice '{voice_id}' is missing.")
        return path

    # ---- Listing ------------------------------------------------------

    def list_voices(self) -> List[VoiceInfo]:
        voices = list(self._builtin_voices().values())
        voices.extend(self._custom_voices.values())
        return voices

    def get_voice(self, voice_id: str) -> VoiceInfo:
        builtin = self._builtin_voices()
        if voice_id in builtin:
            return builtin[voice_id]
        if voice_id in self._custom_voices:
            return self._custom_voices[voice_id]
        raise VoiceNotFoundError(f"Voice '{voice_id}' was not found.")

    # ---- Cloning --------------------------------------------------------

    def register_cloned_voice(self, source_path: Path, name: str) -> VoiceInfo:
        """Persist an uploaded reference clip as a new named custom voice."""
        voice_id = f"custom_{new_id()}"
        custom_dir = self.settings.VOICES_DIR / "custom"
        custom_dir.mkdir(parents=True, exist_ok=True)
        dest = custom_dir / f"{voice_id}.wav"
        shutil.copy(source_path, dest)

        info = VoiceInfo(
            voice_id=voice_id,
            name=name or f"Custom Voice {voice_id[-4:]}",
            gender=VoiceGender.CUSTOM,
            description="User-cloned voice from uploaded reference audio.",
            is_custom=True,
        )
        self._custom_voices[voice_id] = info
        self._save_custom_voices()
        logger.info("Registered cloned voice '%s' (%s)", voice_id, info.name)
        return info

    def delete_cloned_voice(self, voice_id: str) -> None:
        if voice_id not in self._custom_voices:
            raise VoiceNotFoundError(f"Voice '{voice_id}' was not found.")
        path = self.settings.VOICES_DIR / "custom" / f"{voice_id}.wav"
        if path.exists():
            path.unlink()
        del self._custom_voices[voice_id]
        self._save_custom_voices()
        logger.info("Deleted cloned voice '%s'", voice_id)

    # ---- Persistence ------------------------------------------------------

    def _load_custom_voices(self) -> None:
        if not self._registry_path.exists():
            return
        try:
            data = json.loads(self._registry_path.read_text(encoding="utf-8"))
            for item in data:
                info = VoiceInfo(**item)
                self._custom_voices[info.voice_id] = info
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load voice registry: %s", exc)

    def _save_custom_voices(self) -> None:
        try:
            data = [v.model_dump(mode="json") for v in self._custom_voices.values()]
            self._registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist voice registry: %s", exc)


_registry: Optional[VoiceRegistry] = None


def get_voice_registry() -> VoiceRegistry:
    global _registry
    if _registry is None:
        _registry = VoiceRegistry()
    return _registry
