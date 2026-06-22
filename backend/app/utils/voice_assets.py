"""
Default voice asset provisioning.

XTTS-v2 requires a short reference audio clip per speaker to condition
generation on (this is how it achieves voice cloning / multi-speaker
support without separate speaker-embedding training). This module ensures
the two built-in presets (male_default.wav, female_default.wav) exist
under VOICES_DIR.

If the user has not supplied their own curated reference clips, we
synthesize stand-in ones at startup using the OS's built-in or any
locally available neutral TTS voice via pyttsx3 as a bootstrap step, so
the application works immediately out-of-the-box. For production-grade
results, replace these two files with real high-quality human voice
recordings (6-15 seconds, clean, single speaker, minimal background
noise) — see docs/INSTALL.md "Customizing Default Voices".
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)

_BOOTSTRAP_TEXT = (
    "Hello, this is a sample voice reference used to condition natural, "
    "expressive speech synthesis."
)


def ensure_default_voice_assets() -> None:
    settings = get_settings()
    settings.VOICES_DIR.mkdir(parents=True, exist_ok=True)

    male_path = settings.VOICES_DIR / settings.MALE_VOICE_FILE
    female_path = settings.VOICES_DIR / settings.FEMALE_VOICE_FILE

    if male_path.exists() and female_path.exists():
        logger.info("Default voice reference clips found.")
        return

    logger.warning(
        "One or both default voice reference clips are missing. Attempting "
        "to bootstrap placeholder clips with pyttsx3. For best quality, "
        "replace %s and %s with real human voice recordings (see "
        "docs/INSTALL.md).",
        male_path, female_path,
    )

    try:
        _bootstrap_with_pyttsx3(male_path, female_path)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Could not auto-generate placeholder voice clips (%s). "
            "You must manually place %s and %s before generating speech.",
            exc, male_path, female_path,
        )


def _bootstrap_with_pyttsx3(male_path: Path, female_path: Path) -> None:
    import pyttsx3

    engine = pyttsx3.init()
    voices = engine.getProperty("voices")

    male_voice_id = None
    female_voice_id = None
    for v in voices:
        name = (v.name or "").lower()
        v_id = (v.id or "").lower()
        gender_hint = getattr(v, "gender", "") or ""
        if female_voice_id is None and (
            "female" in name or "female" in v_id or "f" == gender_hint.lower()
        ):
            female_voice_id = v.id
        if male_voice_id is None and (
            "male" in name or "male" in v_id or "m" == gender_hint.lower()
        ):
            male_voice_id = v.id

    # Fall back to first two distinct voices if gender heuristics fail
    if male_voice_id is None and voices:
        male_voice_id = voices[0].id
    if female_voice_id is None and len(voices) > 1:
        female_voice_id = voices[1].id
    elif female_voice_id is None and voices:
        female_voice_id = voices[0].id

    if not male_path.exists() and male_voice_id:
        engine.setProperty("voice", male_voice_id)
        engine.save_to_file(_BOOTSTRAP_TEXT, str(male_path))

    if not female_path.exists() and female_voice_id:
        engine.setProperty("voice", female_voice_id)
        engine.save_to_file(_BOOTSTRAP_TEXT, str(female_path))

    engine.runAndWait()

    if male_path.exists():
        logger.info("Bootstrapped placeholder male voice clip at %s", male_path)
    if female_path.exists():
        logger.info("Bootstrapped placeholder female voice clip at %s", female_path)
