"""Static engine catalogue and the system voices seeded for each engine.

Licences are part of the product surface: the API reports them so clients
can pick a commercially usable engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from voix_api.models import Voice, VoiceStatus


@dataclass(frozen=True)
class EngineInfo:
    id: str
    name: str
    license: str
    commercial_use: bool
    supports_cloning: bool
    languages: tuple[str, ...]
    notes: str = ""
    system_voices: tuple[tuple[str, str, str, str], ...] = field(
        default=()
    )  # (engine_voice_id, name, lang, desc)


XTTS_LANGUAGES = (
    "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi",
)  # fmt: skip

ENGINES: dict[str, EngineInfo] = {
    "kokoro": EngineInfo(
        id="kokoro",
        name="Kokoro-82M",
        license="Apache-2.0",
        commercial_use=True,
        supports_cloning=False,
        languages=("en-us", "en-gb"),
        notes="82M-parameter StyleTTS2-derived model; fixed voicepacks, no cloning.",
        system_voices=(
            ("af_heart", "Heart", "en-us", "American English, female, warm"),
            ("af_bella", "Bella", "en-us", "American English, female, bright"),
            ("am_michael", "Michael", "en-us", "American English, male, even"),
            ("am_fenrir", "Fenrir", "en-us", "American English, male, deep"),
            ("bf_emma", "Emma", "en-gb", "British English, female"),
            ("bm_george", "George", "en-gb", "British English, male"),
        ),
    ),
    "xtts": EngineInfo(
        id="xtts",
        name="Coqui XTTS-v2",
        license="Coqui Public Model License 1.0 (non-commercial)",
        commercial_use=False,
        supports_cloning=True,
        languages=XTTS_LANGUAGES,
        notes=(
            "Zero-shot voice cloning from a 3-60s reference clip. "
            "Coqui has shut down; no commercial licence is available."
        ),
        system_voices=(
            ("Ana Florence", "Ana Florence", "en", "XTTS studio speaker, female"),
            ("Claribel Dervla", "Claribel Dervla", "en", "XTTS studio speaker, female"),
            ("Damien Black", "Damien Black", "en", "XTTS studio speaker, male"),
            ("Andrew Chipper", "Andrew Chipper", "en", "XTTS studio speaker, male"),
        ),
    ),
    "mock": EngineInfo(
        id="mock",
        name="Mock tone engine",
        license="MIT (project code)",
        commercial_use=True,
        supports_cloning=True,
        languages=("en",),
        notes="Generates sine tones; exercises the full pipeline on CPU in tests.",
        system_voices=(("tone_a", "Tone A", "en", "440 Hz test voice"),),
    ),
}


def seed_system_voices(db: Session, enabled_engines: list[str]) -> int:
    """Insert any missing system voices for enabled engines. Idempotent."""
    existing = set(
        db.execute(select(Voice.engine, Voice.engine_voice_id).where(Voice.owner_id.is_(None))).all()
    )
    added = 0
    for engine_id in enabled_engines:
        info = ENGINES.get(engine_id)
        if info is None:
            continue
        for voice_id, name, lang, desc in info.system_voices:
            if (engine_id, voice_id) in existing:
                continue
            db.add(
                Voice(
                    owner_id=None,
                    name=name,
                    engine=engine_id,
                    engine_voice_id=voice_id,
                    language=lang,
                    description=desc,
                    status=VoiceStatus.ready,
                )
            )
            added += 1
    db.commit()
    return added
