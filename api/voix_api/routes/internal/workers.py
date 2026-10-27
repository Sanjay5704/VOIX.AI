"""Internal API used by GPU workers (auth: X-Worker-Token).

Workers only ever make *outbound* HTTPS requests, so a worker on a laptop
behind home NAT needs no inbound ports or tunnels.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.orm import Session

from voix_api.config import Settings
from voix_api.db import session_factory, utcnow
from voix_api.errors import ApiError, not_found
from voix_api.models import Job, JobStatus, JobType, Voice, Worker
from voix_api.schemas import (
    ClaimedJob,
    ClaimedVoice,
    ClaimIn,
    JobFailIn,
    JobHeartbeatIn,
    JobHeartbeatOut,
    JobReleaseIn,
    WorkerHello,
)
from voix_api.security.deps import DbDep, SettingsDep, require_worker
from voix_api.services import queue
from voix_api.services.storage import Storage, get_storage

router = APIRouter(
    prefix="/internal",
    tags=["internal (worker)"],
    dependencies=[Depends(require_worker)],
)

StorageDep = Annotated[Storage, Depends(get_storage)]
CLAIM_POLL_INTERVAL = 1.0
AUDIO_TYPES = {"mp3": "audio/mpeg", "wav": "audio/wav"}


def _lease_lost() -> ApiError:
    return ApiError(409, "lease_lost", "Job is no longer leased to this worker")


def _worker(db: Session, name: str) -> Worker:
    return queue.touch_worker(db, name)


@router.post("/workers/heartbeat")
def worker_heartbeat(body: WorkerHello, db: DbDep) -> dict[str, Any]:
    worker = queue.touch_worker(db, body.worker_name, body.engines, body.gpu, body.version)
    db.commit()
    return {"worker_id": str(worker.id), "server_time": utcnow().isoformat()}


def _claimed(job: Job, settings: Settings) -> ClaimedJob:
    voice: Voice | None = job.voice
    claimed_voice = None
    if voice is not None:
        claimed_voice = ClaimedVoice(
            id=voice.id,
            engine=voice.engine,
            engine_voice_id=voice.engine_voice_id,
            language=voice.language,
            reference_url=f"/internal/voices/{voice.id}/reference" if voice.reference_key else None,
            source_url=f"/internal/voices/{voice.id}/source" if voice.source_key else None,
            cache_tag=f"{voice.id}-{voice.reference_key or ''}",
        )
    return ClaimedJob(
        id=job.id,
        type=job.type,
        engine=job.engine,
        attempt=job.attempts,
        params=job.params,
        voice=claimed_voice,
        lease_seconds=settings.lease_seconds,
        lease_expires_at=job.lease_expires_at,
        created_at=job.created_at,
    )


@router.post(
    "/jobs/claim",
    response_model=ClaimedJob,
    responses={204: {"description": "No job available"}},
)
def claim_job(body: ClaimIn, settings: SettingsDep) -> Any:
    """Claim the next job for the worker's engines, long-polling up to `wait_seconds`.

    The DB session is opened per attempt (not held across the wait), so an
    idle long-poll costs no connection.
    """
    deadline = time.monotonic() + min(body.wait_seconds, settings.claim_max_wait_seconds)
    while True:
        with session_factory()() as db:
            worker = queue.touch_worker(db, body.worker_name, body.engines, body.gpu, body.version)
            db.commit()
            job = queue.claim(db, worker, body.engines, settings)
            if job is not None:
                return _claimed(job, settings)
        if time.monotonic() + CLAIM_POLL_INTERVAL > deadline:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        time.sleep(CLAIM_POLL_INTERVAL)


@router.post("/jobs/{job_id}/heartbeat", response_model=JobHeartbeatOut)
def job_heartbeat(
    job_id: uuid.UUID, body: JobHeartbeatIn, db: DbDep, settings: SettingsDep
) -> JobHeartbeatOut:
    worker = _worker(db, body.worker_name)
    try:
        job = queue.heartbeat(db, job_id, worker, body.progress, settings)
    except queue.LeaseLost:
        db.rollback()
        raise _lease_lost() from None
    return JobHeartbeatOut(lease_expires_at=job.lease_expires_at, cancel_requested=job.cancel_requested)


@router.post("/jobs/{job_id}/complete")
def complete_job(
    job_id: uuid.UUID,
    db: DbDep,
    storage: StorageDep,
    worker_name: Annotated[str, Form()],
    result: Annotated[str, Form(description="JSON: job-type specific result + metrics")],
    audio: Annotated[UploadFile | None, File()] = None,
    subtitles: Annotated[UploadFile | None, File()] = None,
    reference: Annotated[UploadFile | None, File()] = None,
) -> dict[str, Any]:
    """Upload result files and mark the job succeeded."""
    try:
        payload: dict[str, Any] = json.loads(result)
    except json.JSONDecodeError:
        raise ApiError(400, "bad_result", "`result` must be JSON") from None

    worker = _worker(db, worker_name)
    job = db.get(Job, job_id)
    if job is None:
        raise not_found("Job")
    if job.worker_id != worker.id:
        raise _lease_lost()

    stored: list[str] = []
    usage = None
    try:
        if job.type == JobType.synthesize:
            fmt = payload.get("format")
            if audio is None or fmt not in AUDIO_TYPES:
                raise ApiError(
                    400,
                    "bad_result",
                    "synthesize results need an audio file and format mp3|wav",
                )
            payload["audio_key"] = f"jobs/{job.id}/audio.{fmt}"
            storage.put(payload["audio_key"], audio.file, AUDIO_TYPES[fmt])
            stored.append(payload["audio_key"])
            if subtitles is not None:
                payload["subtitles_key"] = f"jobs/{job.id}/subtitles.srt"
                storage.put(payload["subtitles_key"], subtitles.file, "application/x-subrip")
                stored.append(payload["subtitles_key"])
            metrics = payload.get("metrics", {})
            usage = {
                "audio_seconds": payload.get("duration_seconds", 0.0),
                "processing_ms": metrics.get("processing_ms", 0),
            }
        else:
            if reference is None:
                raise ApiError(400, "bad_result", "prepare_voice results need a reference file")
            payload["reference_key"] = f"voices/{job.voice_id}/reference.wav"
            storage.put(payload["reference_key"], reference.file, "audio/wav")
            stored.append(payload["reference_key"])

        job = queue.complete(db, job_id, worker, payload, usage)
    except queue.LeaseLost:
        db.rollback()
        for key in stored:
            storage.delete(key)
        raise _lease_lost() from None
    if job.status == JobStatus.canceled:  # user canceled while we were rendering
        for key in stored:
            storage.delete(key)
    return {"status": job.status.value}


@router.post("/jobs/{job_id}/fail")
def fail_job(job_id: uuid.UUID, body: JobFailIn, db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    worker = _worker(db, body.worker_name)
    try:
        job = queue.fail(db, job_id, worker, body.error, body.retryable, settings)
    except queue.LeaseLost:
        db.rollback()
        raise _lease_lost() from None
    return {
        "status": job.status.value,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
    }


@router.post("/jobs/{job_id}/release")
def release_job(job_id: uuid.UUID, body: JobReleaseIn, db: DbDep) -> dict[str, Any]:
    """Return a job to the queue without spending an attempt (worker shutting down)."""
    worker = _worker(db, body.worker_name)
    try:
        job = queue.release(db, job_id, worker)
    except queue.LeaseLost:
        db.rollback()
        raise _lease_lost() from None
    return {"status": job.status.value}


def _voice_file(db: Session, voice_id: uuid.UUID, attr: str, storage: Storage) -> Response:
    voice = db.get(Voice, voice_id)
    key = getattr(voice, attr) if voice else None
    if not key:
        raise not_found("Voice file")
    name = key.rsplit("/", 1)[-1]
    return storage.download_response(key, name, "application/octet-stream")


@router.get("/voices/{voice_id}/reference", response_class=Response)
def voice_reference(voice_id: uuid.UUID, db: DbDep, storage: StorageDep) -> Response:
    return _voice_file(db, voice_id, "reference_key", storage)


@router.get("/voices/{voice_id}/source", response_class=Response)
def voice_source(voice_id: uuid.UUID, db: DbDep, storage: StorageDep) -> Response:
    return _voice_file(db, voice_id, "source_key", storage)
