"""SQLAlchemy 2.0 ORM models.

The `jobs` table doubles as the work queue (see services/queue.py); its
composite index on (status, engine, priority, created_at) is what the
claim query walks.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import false as sa_false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from voix_api.db import Base, UTCDateTime, utcnow

JSONType = JSON().with_variant(JSONB(), "postgresql")
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")  # SQLite only autoincrements INTEGER


class JobType(str, enum.Enum):
    synthesize = "synthesize"
    prepare_voice = "prepare_voice"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


TERMINAL_STATUSES = (JobStatus.succeeded, JobStatus.failed, JobStatus.canceled)


class VoiceStatus(str, enum.Enum):
    pending = "pending"
    ready = "ready"
    failed = "failed"


def _enum(e: type[enum.Enum], name: str):
    from sqlalchemy import Enum

    # Stored as VARCHAR + CHECK rather than a native PG enum: adding a value
    # later is then a plain migration instead of an ALTER TYPE dance.
    return Enum(
        e,
        name=name,
        native_enum=False,
        length=32,
        validate_strings=True,
        create_constraint=True,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    plan: Mapped[str] = mapped_column(String(32), default="free")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64))  # sha256 hex of the full key
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship()


class Voice(Base):
    __tablename__ = "voices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )  # NULL = system voice
    name: Mapped[str] = mapped_column(String(100))
    engine: Mapped[str] = mapped_column(String(32))
    engine_voice_id: Mapped[str | None] = mapped_column(String(100))  # built-in speaker/voicepack
    language: Mapped[str] = mapped_column(String(16), default="en")
    description: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[VoiceStatus] = mapped_column(
        _enum(VoiceStatus, "voice_status"), default=VoiceStatus.pending
    )
    source_key: Mapped[str | None] = mapped_column(String(300))
    reference_key: Mapped[str | None] = mapped_column(String(300))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    consent_statement: Mapped[str | None] = mapped_column(Text)
    consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    consent_ip: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("engine", "engine_voice_id", name="uq_voices_engine_voice"),)

    @property
    def is_system(self) -> bool:
        return self.owner_id is None


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    engines: Mapped[list[str]] = mapped_column(JSONType, default=list)
    gpu: Mapped[str | None] = mapped_column(String(200))
    version: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    voice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voices.id", ondelete="SET NULL"))
    type: Mapped[JobType] = mapped_column(_enum(JobType, "job_type"))
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus, "job_status"), default=JobStatus.queued)
    engine: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime | None] = mapped_column(UTCDateTime)  # retry backoff
    worker_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workers.id", ondelete="SET NULL"))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # latest claim
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    voice: Mapped[Voice | None] = relationship()
    worker: Mapped[Worker | None] = relationship()

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_jobs_user_idempotency"),
        Index("ix_jobs_claim", "status", "engine", "priority", "created_at"),
        Index("ix_jobs_user_created", "user_id", "created_at"),
        Index("ix_jobs_status_lease", "status", "lease_expires_at"),
    )


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    engine: Mapped[str] = mapped_column(String(32))
    chars: Mapped[int] = mapped_column(Integer)
    audio_seconds: Mapped[float] = mapped_column(Float)
    queue_ms: Mapped[int] = mapped_column(Integer)
    processing_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (Index("ix_usage_user_created", "user_id", "created_at"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(200))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class BenchmarkRun(Base):
    """One offline engine benchmark, uploaded by a worker host.

    `results` holds the full per-engine, per-script measurements; the API
    serves the latest run to the dashboard and folds a summary into /v1/engines.
    """

    __tablename__ = "benchmark_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    host: Mapped[str] = mapped_column(String(100))
    hardware: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    results: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
