from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import or_, select

from voix_api.db import utcnow
from voix_api.errors import ApiError, not_found
from voix_api.models import Job, JobStatus, JobType, Voice, VoiceStatus
from voix_api.schemas import VoiceCloneOut, VoiceOut
from voix_api.security.deps import DbDep, PrincipalDep, SettingsDep, client_ip
from voix_api.services import audit, limits
from voix_api.services.catalog import ENGINES
from voix_api.services.storage import Storage, get_storage

router = APIRouter(prefix="/voices", tags=["voices"])

ALLOWED_EXTENSIONS = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
}
MIN_CONSENT_STATEMENT = 20
PREPARE_PRIORITY_BOOST = 5  # clone prep is seconds of ffmpeg; don't park it behind long renders

StorageDep = Annotated[Storage, Depends(get_storage)]


def visible_voice(db, voice_id: uuid.UUID, user_id: uuid.UUID) -> Voice:
    voice = db.get(Voice, voice_id)
    if voice is None or (voice.owner_id is not None and voice.owner_id != user_id):
        raise not_found("Voice")
    return voice


@router.get("", response_model=list[VoiceOut])
def list_voices(db: DbDep, principal: PrincipalDep, settings: SettingsDep) -> list[Voice]:
    """System voices for enabled engines, plus the caller's own clones."""
    stmt = (
        select(Voice)
        .where(
            Voice.engine.in_(settings.enabled_engines),
            or_(Voice.owner_id.is_(None), Voice.owner_id == principal.user_id),
        )
        .order_by(Voice.owner_id.is_(None).desc(), Voice.engine, Voice.name)
    )
    return list(db.scalars(stmt))


@router.get("/{voice_id}", response_model=VoiceOut)
def get_voice(voice_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> Voice:
    return visible_voice(db, voice_id, principal.user_id)


@router.post("", response_model=VoiceCloneOut, status_code=status.HTTP_202_ACCEPTED)
def clone_voice(
    request: Request,
    db: DbDep,
    principal: PrincipalDep,
    settings: SettingsDep,
    storage: StorageDep,
    name: Annotated[str, Form(min_length=1, max_length=100)],
    file: Annotated[UploadFile, File(description="3-60 s of clean speech (wav/mp3/flac/ogg/m4a)")],
    consent: Annotated[
        bool,
        Form(description="I have the speaker's explicit permission to clone this voice"),
    ],
    consent_statement: Annotated[str, Form(max_length=2000)],
    language: Annotated[str, Form(max_length=16)] = "en",
) -> VoiceCloneOut:
    """Upload a reference clip to clone a voice. Requires recorded consent.

    Returns 202: the clip is standardised by a worker (`prepare_voice` job)
    and the voice becomes `ready` once that job succeeds.
    """
    if not consent or len(consent_statement.strip()) < MIN_CONSENT_STATEMENT:
        raise ApiError(
            400,
            "consent_required",
            "Voice cloning requires consent=true and a consent statement describing the speaker's permission "
            f"(at least {MIN_CONSENT_STATEMENT} characters)",
        )
    engine = settings.clone_engine
    if engine not in settings.enabled_engines or not ENGINES[engine].supports_cloning:
        raise ApiError(
            400,
            "cloning_unavailable",
            "Voice cloning is not enabled on this deployment",
        )

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ApiError(
            415,
            "unsupported_media",
            f"Unsupported file type; allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    limits.lock_user(db, principal.user_id)
    limits.enforce_rate_limit(db, principal.user_id, settings)

    now = utcnow()
    ip = client_ip(request)
    voice = Voice(
        owner_id=principal.user_id,
        name=name.strip(),
        engine=engine,
        language=language,
        status=VoiceStatus.pending,
        description="Cloned voice",
        consent_statement=consent_statement.strip(),
        consent_at=now,
        consent_ip=ip,
    )
    db.add(voice)
    db.flush()

    voice.source_key = f"voices/{voice.id}/source{ext}"
    size = _store_upload_capped(
        file,
        storage,
        voice.source_key,
        ALLOWED_EXTENSIONS[ext],
        settings.max_upload_bytes,
    )

    job = Job(
        user_id=principal.user_id,
        voice_id=voice.id,
        type=JobType.prepare_voice,
        status=JobStatus.queued,
        engine=engine,
        params={"source_ext": ext},
        char_count=0,
        priority=settings.plan_priorities.get(principal.user.plan, 0) + PREPARE_PRIORITY_BOOST,
        max_attempts=settings.default_max_attempts,
    )
    db.add(job)
    db.flush()
    audit.record(
        db,
        "voice.clone_consent",
        user_id=principal.user_id,
        target=str(voice.id),
        ip=ip,
        statement=voice.consent_statement,
        filename=file.filename,
        bytes=size,
        via=principal.via,
    )
    db.commit()
    return VoiceCloneOut(voice=VoiceOut.model_validate(voice), job_id=job.id)


@router.delete("/{voice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voice(
    voice_id: uuid.UUID,
    request: Request,
    db: DbDep,
    principal: PrincipalDep,
    storage: StorageDep,
) -> Response:
    voice = visible_voice(db, voice_id, principal.user_id)
    if voice.is_system:
        raise ApiError(403, "forbidden", "System voices cannot be deleted")
    keys = [k for k in (voice.source_key, voice.reference_key) if k]
    audit.record(
        db,
        "voice.delete",
        user_id=principal.user_id,
        target=str(voice.id),
        ip=client_ip(request),
    )
    db.delete(voice)
    db.commit()
    for key in keys:  # after commit: a dangling object is harmless, a dangling row is not
        storage.delete(key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _store_upload_capped(
    upload: UploadFile, storage: Storage, key: str, content_type: str, max_bytes: int
) -> int:
    """Copy the upload to storage, refusing anything over `max_bytes` without
    trusting Content-Length."""
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as buf:
        total = 0
        while chunk := upload.file.read(1024 * 1024):
            total += len(chunk)
            if total > max_bytes:
                raise ApiError(
                    413,
                    "file_too_large",
                    f"Upload exceeds {max_bytes // (1024 * 1024)} MB",
                )
            buf.write(chunk)
        if total == 0:
            raise ApiError(400, "empty_file", "Uploaded file is empty")
        buf.seek(0)
        storage.put(key, buf, content_type)
        return total
