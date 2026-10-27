r"""Postgres-backed job queue: the `jobs` table is the queue.

Lifecycle::

    queued --claim--> running --complete--> succeeded
       ^                 |  \--fail(permanent) / attempts exhausted--> failed
       |                 |  \--cancel requested--> canceled
       +--retry/reap-----+

* **Claim** uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so any number of
  workers can poll concurrently without double-claiming or blocking on each
  other. A claim takes a *lease* (``lease_expires_at``).
* **Heartbeats** from the worker extend the lease while a job runs.
* **Reaping** is lazy: there is no background scheduler. Every claim (and the
  health check) first requeues running jobs whose lease expired - the worker
  crashed, lost Wi-Fi, or the laptop went to sleep - until ``max_attempts``
  is reached, then fails them.
* **Retries** back off exponentially via ``run_after``.

On SQLite (local tests) ``FOR UPDATE SKIP LOCKED`` is silently dropped; that is
fine there because SQLite serialises writers anyway.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from voix_api.config import Settings
from voix_api.db import utcnow
from voix_api.models import (
    TERMINAL_STATUSES,
    Job,
    JobStatus,
    JobType,
    UsageEvent,
    VoiceStatus,
    Worker,
)

REAP_BATCH = 100


class LeaseLost(Exception):
    """The worker no longer owns this job (reaped, canceled or reassigned)."""


@dataclass
class ReapResult:
    requeued: int = 0
    failed: int = 0
    canceled: int = 0


# --- Workers ----------------------------------------------------------------


def touch_worker(
    db: Session,
    name: str,
    engines: list[str] | None = None,
    gpu: str | None = None,
    version: str | None = None,
) -> Worker:
    worker = db.scalar(select(Worker).where(Worker.name == name))
    if worker is None:
        worker = Worker(name=name, engines=engines or [])
        db.add(worker)
    if engines is not None:
        worker.engines = list(engines)
    if gpu is not None:
        worker.gpu = gpu
    if version is not None:
        worker.version = version
    worker.last_seen_at = utcnow()
    db.flush()
    return worker


def online_workers(db: Session, settings: Settings) -> list[Worker]:
    cutoff = utcnow() - timedelta(seconds=settings.worker_online_seconds)
    return list(db.scalars(select(Worker).where(Worker.last_seen_at >= cutoff).order_by(Worker.name)))


# --- Reaping ----------------------------------------------------------------


def reap_expired(db: Session, now: datetime | None = None) -> ReapResult:
    """Requeue or fail running jobs whose lease has expired. Commits."""
    now = now or utcnow()
    result = ReapResult()
    expired = db.scalars(
        select(Job)
        .where(Job.status == JobStatus.running, Job.lease_expires_at < now)
        .limit(REAP_BATCH)
        .with_for_update(skip_locked=True)
    ).all()
    for job in expired:
        if job.cancel_requested:
            _finish(job, JobStatus.canceled, now, error="canceled (worker lost)")
            result.canceled += 1
        elif job.attempts < job.max_attempts:
            _requeue(
                job,
                now,
                error=f"lease expired on attempt {job.attempts}; requeued",
                backoff=None,
            )
            result.requeued += 1
        else:
            _finish(
                job,
                JobStatus.failed,
                now,
                error=f"lease expired; gave up after {job.attempts} attempts",
            )
            result.failed += 1
    db.commit()
    return result


# --- Claim ------------------------------------------------------------------


def claim(db: Session, worker: Worker, engines: list[str], settings: Settings) -> Job | None:
    """Atomically take the next runnable job for these engines. Commits."""
    reap_expired(db)
    now = utcnow()
    job = db.scalar(
        select(Job)
        .where(
            Job.status == JobStatus.queued,
            Job.engine.in_(engines),
            or_(Job.run_after.is_(None), Job.run_after <= now),
        )
        .order_by(Job.priority.desc(), Job.created_at, Job.id)  # id: deterministic tiebreak
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        db.commit()
        return None
    job.status = JobStatus.running
    job.worker_id = worker.id
    job.attempts += 1
    job.started_at = now
    job.lease_expires_at = now + timedelta(seconds=settings.lease_seconds)
    job.progress = 0.0
    job.run_after = None
    db.commit()
    return job


# --- Worker-side transitions ----------------------------------------------------


def _owned_running_job(db: Session, job_id: uuid.UUID, worker: Worker) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None or job.status != JobStatus.running or job.worker_id != worker.id:
        raise LeaseLost(str(job_id))
    return job


def heartbeat(
    db: Session,
    job_id: uuid.UUID,
    worker: Worker,
    progress: float | None,
    settings: Settings,
) -> Job:
    """Extend the lease. Returns the job so the worker can see `cancel_requested`."""
    job = _owned_running_job(db, job_id, worker)
    job.lease_expires_at = utcnow() + timedelta(seconds=settings.lease_seconds)
    if progress is not None:
        job.progress = max(0.0, min(1.0, progress))
    db.commit()
    return job


def complete(
    db: Session,
    job_id: uuid.UUID,
    worker: Worker,
    result: dict[str, Any],
    usage: dict[str, Any] | None = None,
) -> Job:
    job = _owned_running_job(db, job_id, worker)
    now = utcnow()
    if job.cancel_requested:
        _finish(job, JobStatus.canceled, now, error="canceled")
        db.commit()
        return job

    job.result = result
    job.progress = 1.0
    _finish(job, JobStatus.succeeded, now)

    if job.type == JobType.prepare_voice and job.voice is not None:
        job.voice.status = VoiceStatus.ready
        job.voice.reference_key = result.get("reference_key")
        job.voice.duration_seconds = result.get("duration_seconds")
        job.voice.error = None

    if job.type == JobType.synthesize and usage is not None:
        queue_ms = int((job.started_at - job.created_at).total_seconds() * 1000) if job.started_at else 0
        db.add(
            UsageEvent(
                user_id=job.user_id,
                job_id=job.id,
                engine=job.engine,
                chars=job.char_count,
                audio_seconds=float(usage.get("audio_seconds", 0.0)),
                queue_ms=max(0, queue_ms),
                processing_ms=int(usage.get("processing_ms", 0)),
            )
        )
    db.commit()
    return job


def fail(
    db: Session,
    job_id: uuid.UUID,
    worker: Worker,
    error: str,
    retryable: bool,
    settings: Settings,
) -> Job:
    job = _owned_running_job(db, job_id, worker)
    now = utcnow()
    if job.cancel_requested:
        _finish(job, JobStatus.canceled, now, error="canceled")
    elif retryable and job.attempts < job.max_attempts:
        backoff = timedelta(seconds=settings.retry_backoff_seconds * 2 ** (job.attempts - 1))
        _requeue(job, now, error=error, backoff=backoff)
    else:
        _finish(job, JobStatus.failed, now, error=error)
    db.commit()
    return job


def release(db: Session, job_id: uuid.UUID, worker: Worker) -> Job:
    """Hand a job back without spending an attempt (graceful worker shutdown)."""
    job = _owned_running_job(db, job_id, worker)
    job.attempts = max(0, job.attempts - 1)
    _requeue(job, utcnow(), error="released by worker shutdown", backoff=None)
    db.commit()
    return job


# --- User-side transitions ------------------------------------------------------


def request_cancel(db: Session, job: Job) -> Job:
    """Queued jobs cancel immediately; running ones are flagged for the worker."""
    if job.status in TERMINAL_STATUSES:
        return job
    if job.status == JobStatus.queued:
        _finish(job, JobStatus.canceled, utcnow(), error="canceled")
    else:
        job.cancel_requested = True
    db.commit()
    return job


# --- helpers ----------------------------------------------------------------


def _requeue(job: Job, now: datetime, error: str, backoff: timedelta | None) -> None:
    job.status = JobStatus.queued
    job.worker_id = None
    job.lease_expires_at = None
    job.error = error
    job.progress = 0.0
    job.run_after = now + backoff if backoff else None


def _finish(job: Job, status: JobStatus, now: datetime, error: str | None = None) -> None:
    job.status = status
    job.finished_at = now
    job.lease_expires_at = None
    if error is not None:
        job.error = error
    # A clone whose preparation didn't succeed can never be used.
    if status != JobStatus.succeeded and job.type == JobType.prepare_voice and job.voice is not None:
        job.voice.status = VoiceStatus.failed
        job.voice.error = error
