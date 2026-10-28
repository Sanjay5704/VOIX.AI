"""
Voice registry.

Lists the built-in voices of each enabled engine plus any user-cloned voices,
and resolves a voice id to (engine, VoiceRef). Cloned voices are stored as
reference clips under VOICES_DIR/custom with their names in
voice_registry.json, so they survive restarts.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import get_settings
from app.core.exceptions import VoiceNotFoundError
from app.core.logging_config import get_logger
from app.models.schemas import EngineName, VoiceGender, VoiceInfo
from app.services.engines import VoiceRef
from app.utils.file_manager import new_id

logger = get_logger(__name__)

_REGISTRY_FILE = "voice_registry.json"


# Built-in voices. Kokoro voice ids are its voicepack names; XTTS ones map to
# the studio speakers that ship inside the XTTS-v2 checkpoint (no files needed).
_KOKORO_VOICES = [
    ("af_heart", "Heart", VoiceGender.FEMALE, "en-us", "American English, warm"),
    ("af_bella", "Bella", VoiceGender.FEMALE, "en-us", "American English, bright"),
    ("am_michael", "Michael", VoiceGender.MALE, "en-us", "American English, even"),
    ("am_fenrir", "Fenrir", VoiceGender.MALE, "en-us", "American English, deep"),
    ("bf_emma", "Emma", VoiceGender.FEMALE, "en-gb", "British English"),
    ("bm_george", "George", VoiceGender.MALE, "en-gb", "British English"),
]
_XTTS_SPEAKERS = [
    ("xtts_ana", "Ana Florence", VoiceGender.FEMALE, "Multilingual studio voice"),
    ("xtts_claribel", "Claribel Dervla", VoiceGender.FEMALE, "Multilingual studio voice"),
    ("xtts_damien", "Damien Black", VoiceGender.MALE, "Multilingual studio voice"),
    ("xtts_andrew", "Andrew Chipper", VoiceGender.MALE, "Multilingual studio voice"),
]


class VoiceRegistry:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._registry_path = self.settings.VOICES_DIR / _REGISTRY_FILE
        self._custom_voices: Dict[str, VoiceInfo] = {}
        self._load_custom_voices()

    # ---- Built-in voices --------------------------------------------------

    def _builtin_voices(self) -> Dict[str, VoiceInfo]:
        voices: Dict[str, VoiceInfo] = {}
        enabled = self.settings.ENABLED_ENGINES
        if "kokoro" in enabled:
            for vid, name, gender, lang, desc in _KOKORO_VOICES:
                voices[vid] = VoiceInfo(
                    voice_id=vid, name=name, gender=gender, description=desc,
                    engine=EngineName.KOKORO, language=lang,
                )  # fmt: skip
        if "xtts" in enabled:
            for vid, name, gender, desc in _XTTS_SPEAKERS:
                voices[vid] = VoiceInfo(
                    voice_id=vid, name=name, gender=gender, description=desc, engine=EngineName.XTTS
                )
        return voices

    def resolve(self, voice_id: str) -> tuple[EngineName, VoiceRef]:
        """Which engine speaks this voice, and how (built-in speaker or cloned clip)."""
        info = self.get_voice(voice_id)
        if info.engine.value not in self.settings.ENABLED_ENGINES:
            raise VoiceNotFoundError(
                f"Voice '{voice_id}' needs the {info.engine.value} engine, which is disabled."
            )
        if info.engine == EngineName.KOKORO:
            return info.engine, VoiceRef(speaker=voice_id)
        if not info.is_custom:
            return info.engine, VoiceRef(speaker=info.name)  # XTTS studio speaker
        path = self.settings.VOICES_DIR / "custom" / f"{voice_id}.wav"
        if not path.exists():
            raise VoiceNotFoundError(f"Reference clip for voice '{voice_id}' is missing.")
        return info.engine, VoiceRef(reference_wav=path)

    # ---- Listing ------------------------------------------------------

    def list_voices(self) -> List[VoiceInfo]:
        voices = list(self._builtin_voices().values())
        if "xtts" in self.settings.ENABLED_ENGINES:  # cloned voices are spoken by XTTS
            voices.extend(self._custom_voices.values())
        return voices

    def get_voice(self, voice_id: str) -> VoiceInfo:
        builtin = self._builtin_voices()
        if voice_id in builtin:
            return builtin[voice_id]
        if voice_id in self._custom_voices:
            return self._custom_voices[voice_id]
        raise VoiceNotFoundError(f"Voice '{voice_id}' was not found.")

    def is_builtin(self, voice_id: str) -> bool:
        return voice_id in self._builtin_voices()

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
            engine=EngineName.XTTS,
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
