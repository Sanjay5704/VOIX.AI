from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from voix_api.errors import ApiError, not_found
from voix_api.models import Job, JobStatus, JobType, VoiceStatus
from voix_api.observability import JOBS_CREATED
from voix_api.schemas import JobOut, Page, TTSJobIn
from voix_api.security.deps import DbDep, PrincipalDep, SettingsDep, client_ip
from voix_api.services import audit, limits, queue
from voix_api.services.storage import Storage, get_storage

from .voices import visible_voice

router = APIRouter(prefix="/jobs", tags=["jobs"])

StorageDep = Annotated[Storage, Depends(get_storage)]
MEDIA_TYPES = {"mp3": "audio/mpeg", "wav": "audio/wav"}
_PRIVATE_RESULT_KEYS = {"audio_key", "subtitles_key", "reference_key"}


def job_out(job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    if job.result:
        out.result = {k: v for k, v in job.result.items() if k not in _PRIVATE_RESULT_KEYS}
        if job.status == JobStatus.succeeded and job.type == JobType.synthesize:
            out.audio_url = f"/v1/jobs/{job.id}/audio"
            if job.result.get("subtitles_key"):
                out.subtitles_url = f"/v1/jobs/{job.id}/subtitles"
    return out


def _request_hash(body: TTSJobIn) -> str:
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _idempotent_replay(db: Session, user_id: uuid.UUID, key: str, request_hash: str) -> Job | None:
    existing = db.scalar(select(Job).where(Job.user_id == user_id, Job.idempotency_key == key))
    if existing is None:
        return None
    if existing.request_hash != request_hash:
        raise ApiError(
            409,
            "idempotency_conflict",
            "Idempotency-Key was already used with a different request body",
        )
    return existing


@router.post("/tts", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def create_tts_job(
    body: TTSJobIn,
    request: Request,
    response: Response,
    db: DbDep,
    principal: PrincipalDep,
    settings: SettingsDep,
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
) -> JobOut:
    """Queue a text-to-speech job. Returns 202 immediately; poll `GET /v1/jobs/{id}`.

    Send an `Idempotency-Key` header to make retries safe: repeating the same
    request returns the original job (200) instead of creating a new one.
    """
    req_hash = _request_hash(body)
    if idempotency_key:
        replay = _idempotent_replay(db, principal.user_id, idempotency_key, req_hash)
        if replay is not None:
            response.status_code = status.HTTP_200_OK
            return job_out(replay)

    if len(body.text) > settings.max_text_chars:
        raise ApiError(
            413,
            "text_too_long",
            f"Text is {len(body.text)} characters; the per-job limit is {settings.max_text_chars}",
        )
    voice = visible_voice(db, body.voice_id, principal.user_id)
    if voice.status != VoiceStatus.ready:
        raise ApiError(409, "voice_not_ready", f"Voice is {voice.status.value}")
    if voice.engine not in settings.enabled_engines:
        raise ApiError(409, "engine_disabled", f"Engine '{voice.engine}' is not enabled")

    chars = len(body.text)
    limits.lock_user(db, principal.user_id)
    limits.enforce_rate_limit(db, principal.user_id, settings)
    limits.enforce_quota(db, principal.user, chars, settings)

    params: dict[str, Any] = body.model_dump(mode="json", exclude={"voice_id"})
    params["language"] = body.language or voice.language
    job = Job(
        user_id=principal.user_id,
        voice_id=voice.id,
        type=JobType.synthesize,
        status=JobStatus.queued,
        engine=voice.engine,
        params=params,
        char_count=chars,
        priority=settings.plan_priorities.get(principal.user.plan, 0),
        max_attempts=settings.default_max_attempts,
        idempotency_key=idempotency_key,
        request_hash=req_hash,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with a concurrent request carrying the same key.
        db.rollback()
        replay = _idempotent_replay(db, principal.user_id, idempotency_key or "", req_hash)
        if replay is None:
            raise
        response.status_code = status.HTTP_200_OK
        return job_out(replay)

    JOBS_CREATED.labels("synthesize", job.engine).inc()
    response.headers["Location"] = f"/v1/jobs/{job.id}"
    return job_out(job)


def _encode_cursor(job: Job) -> str:
    return base64.urlsafe_b64encode(f"{job.created_at.isoformat()}|{job.id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created, job_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(created), uuid.UUID(job_id)
    except Exception:
        raise ApiError(400, "invalid_cursor", "Malformed pagination cursor") from None


@router.get("", response_model=Page[JobOut])
def list_jobs(
    db: DbDep,
    principal: PrincipalDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    type_filter: Annotated[JobType | None, Query(alias="type")] = None,
) -> Page[JobOut]:
    """Newest first, keyset-paginated: pass `next_cursor` back as `cursor`."""
    stmt = select(Job).where(Job.user_id == principal.user_id)
    if status_filter:
        stmt = stmt.where(Job.status == status_filter)
    if type_filter:
        stmt = stmt.where(Job.type == type_filter)
    if cursor:
        c_created, c_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Job.created_at < c_created,
                and_(Job.created_at == c_created, Job.id < c_id),
            )
        )
    rows = list(db.scalars(stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit + 1)))
    has_more = len(rows) > limit
    rows = rows[:limit]
    return Page[JobOut](
        items=[job_out(j) for j in rows],
        next_cursor=_encode_cursor(rows[-1]) if has_more else None,
    )


def _own_job(db: Session, job_id: uuid.UUID, user_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.user_id != user_id:
        raise not_found("Job")
    return job


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> JobOut:
    return job_out(_own_job(db, job_id, principal.user_id))


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: uuid.UUID, request: Request, db: DbDep, principal: PrincipalDep) -> JobOut:
    """Queued jobs cancel immediately; running jobs stop at the worker's next heartbeat."""
    job = _own_job(db, job_id, principal.user_id)
    if job.status in (JobStatus.succeeded, JobStatus.failed):
        raise ApiError(409, "job_finished", f"Job already {job.status.value}")
    audit.record(
        db,
        "job.cancel",
        user_id=principal.user_id,
        target=str(job.id),
        ip=client_ip(request),
    )
    return job_out(queue.request_cancel(db, job))


def _download(job: Job, key_name: str, storage: Storage) -> Response:
    if job.status != JobStatus.succeeded or not job.result or not job.result.get(key_name):
        raise ApiError(
            409,
            "not_ready",
            "Job has no such output (not finished, or subtitles disabled)",
        )
    key = job.result[key_name]
    if key_name == "subtitles_key":
        return storage.download_response(key, f"voix-{str(job.id)[:8]}.srt", "application/x-subrip")
    fmt = job.result.get("format", "mp3")
    return storage.download_response(
        key,
        f"voix-{str(job.id)[:8]}.{fmt}",
        MEDIA_TYPES.get(fmt, "application/octet-stream"),
    )


@router.get(
    "/{job_id}/audio",
    response_class=Response,
    responses={200: {"content": {"audio/mpeg": {}}}, 302: {}},
)
def download_audio(job_id: uuid.UUID, db: DbDep, principal: PrincipalDep, storage: StorageDep) -> Response:
    return _download(_own_job(db, job_id, principal.user_id), "audio_key", storage)


@router.get(
    "/{job_id}/subtitles",
    response_class=Response,
    responses={200: {"content": {"application/x-subrip": {}}}, 302: {}},
)
def download_subtitles(
    job_id: uuid.UUID, db: DbDep, principal: PrincipalDep, storage: StorageDep
) -> Response:
    return _download(_own_job(db, job_id, principal.user_id), "subtitles_key", storage)
