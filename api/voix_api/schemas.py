"""Pydantic request/response models for the public and internal APIs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from voix_api.models import JobStatus, JobType, VoiceStatus

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


# --- Auth -------------------------------------------------------------------


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def _bcrypt_limit(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 bytes")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORM):
    id: uuid.UUID
    email: str
    plan: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut


# --- API keys ---------------------------------------------------------------


class ApiKeyCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyOut(ORM):
    id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreatedOut(ApiKeyOut):
    key: str = Field(description="Full key. Shown once; store it now.")


# --- Voices -----------------------------------------------------------------


class VoiceOut(ORM):
    id: uuid.UUID
    name: str
    engine: str
    language: str
    description: str | None
    status: VoiceStatus
    is_system: bool
    duration_seconds: float | None
    error: str | None
    created_at: datetime


class VoiceCloneOut(BaseModel):
    voice: VoiceOut
    job_id: uuid.UUID


# --- Jobs -------------------------------------------------------------------


class TTSJobIn(BaseModel):
    text: str = Field(min_length=1)
    voice_id: uuid.UUID
    language: str | None = Field(default=None, description="Defaults to the voice's language")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch_semitones: float = Field(default=0.0, ge=-12, le=12)
    expressiveness: float = Field(
        default=1.0, ge=0.5, le=1.5, description="XTTS only: sampling temperature scale"
    )
    output_format: Literal["mp3", "wav"] = "mp3"
    subtitles: bool = True

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be blank")
        return v


class JobOut(ORM):
    id: uuid.UUID
    type: JobType
    status: JobStatus
    engine: str
    voice_id: uuid.UUID | None
    char_count: int
    progress: float
    attempts: int
    max_attempts: int
    cancel_requested: bool
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    params: dict[str, Any]
    result: dict[str, Any] | None = None
    audio_url: str | None = None
    subtitles_url: str | None = None


# --- Usage / health / engines ----------------------------------------------------


class LimitsOut(BaseModel):
    max_text_chars: int
    max_upload_mb: int
    rate_limit_jobs_per_minute: int


class UsageOut(BaseModel):
    plan: str
    period_start: datetime
    period_end: datetime
    chars_used: int
    chars_quota: int
    chars_remaining: int
    audio_seconds: float
    jobs_succeeded: int
    limits: LimitsOut


class WorkerOut(ORM):
    name: str
    engines: list[str]
    gpu: str | None
    version: str | None
    last_seen_at: datetime


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
    workers_online: int
    workers: list[WorkerOut]
    queue_depth: int


class EngineOut(BaseModel):
    id: str
    name: str
    license: str
    commercial_use: bool
    supports_cloning: bool
    languages: list[str]
    notes: str
    online: bool


# --- Internal (worker) API -------------------------------------------------------


class WorkerHello(BaseModel):
    worker_name: str = Field(min_length=1, max_length=100)
    engines: list[str] = Field(default_factory=list)
    gpu: str | None = None
    version: str | None = None


class ClaimIn(WorkerHello):
    wait_seconds: float = Field(default=0, ge=0, le=60)


class ClaimedVoice(BaseModel):
    id: uuid.UUID
    engine: str
    engine_voice_id: str | None
    language: str
    reference_url: str | None
    source_url: str | None
    cache_tag: str  # changes whenever the reference clip changes


class ClaimedJob(BaseModel):
    id: uuid.UUID
    type: JobType
    engine: str
    attempt: int
    params: dict[str, Any]
    voice: ClaimedVoice | None
    lease_seconds: int
    lease_expires_at: datetime
    created_at: datetime


class JobHeartbeatIn(BaseModel):
    worker_name: str
    progress: float | None = Field(default=None, ge=0, le=1)


class JobHeartbeatOut(BaseModel):
    lease_expires_at: datetime
    cancel_requested: bool


class JobFailIn(BaseModel):
    worker_name: str
    error: str = Field(max_length=4000)
    retryable: bool = False


class JobReleaseIn(BaseModel):
    worker_name: str
