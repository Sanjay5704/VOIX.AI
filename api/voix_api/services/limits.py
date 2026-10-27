"""Plan quotas and per-user rate limiting, both computed from the database.

Deriving limits from `jobs` (instead of in-process counters or Redis) keeps
them correct across any number of API instances. Callers take
`lock_user()` first, so two concurrent requests from the same user are
serialised and can't both squeeze under the limit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from voix_api.config import Settings
from voix_api.db import utcnow
from voix_api.errors import ApiError
from voix_api.models import Job, JobStatus, JobType, UsageEvent, User

RATE_WINDOW = timedelta(seconds=60)


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


def lock_user(db: Session, user_id: uuid.UUID) -> None:
    """Row-lock the user for the rest of the transaction (no-op on SQLite)."""
    db.execute(select(User.id).where(User.id == user_id).with_for_update())


def chars_used_this_month(db: Session, user_id: uuid.UUID, now: datetime | None = None) -> int:
    """Characters reserved by this month's synth jobs. Failed/canceled jobs
    release their reservation automatically."""
    start, _ = month_bounds(now or utcnow())
    used = db.scalar(
        select(func.coalesce(func.sum(Job.char_count), 0)).where(
            Job.user_id == user_id,
            Job.type == JobType.synthesize,
            Job.created_at >= start,
            Job.status.not_in([JobStatus.failed, JobStatus.canceled]),
        )
    )
    return int(used or 0)


def quota_for(user: User, settings: Settings) -> int:
    return settings.plan_quotas.get(user.plan, settings.plan_quotas["free"])


def enforce_quota(db: Session, user: User, chars: int, settings: Settings) -> None:
    quota = quota_for(user, settings)
    used = chars_used_this_month(db, user.id)
    if used + chars > quota:
        raise ApiError(
            402,
            "quota_exceeded",
            f"Monthly character quota exceeded ({used} used + {chars} requested > {quota})",
            {"used": used, "requested": chars, "quota": quota, "plan": user.plan},
        )


def enforce_rate_limit(db: Session, user_id: uuid.UUID, settings: Settings) -> None:
    now = utcnow()
    window_start = now - RATE_WINDOW
    recent = db.execute(
        select(func.count(Job.id), func.min(Job.created_at)).where(
            Job.user_id == user_id, Job.created_at > window_start
        )
    ).one()
    count, oldest = int(recent[0]), recent[1]
    limit = settings.rate_limit_jobs_per_minute
    if count >= limit:
        retry_after = max(1, int(((oldest + RATE_WINDOW) - now).total_seconds()) + 1) if oldest else 60
        raise ApiError(
            429,
            "rate_limited",
            f"Rate limit exceeded: {limit} jobs per minute",
            {"limit": limit, "window_seconds": int(RATE_WINDOW.total_seconds())},
            headers={"Retry-After": str(retry_after)},
        )


@dataclass
class UsageSummary:
    plan: str
    period_start: datetime
    period_end: datetime
    chars_used: int
    chars_quota: int
    audio_seconds: float
    jobs_succeeded: int


def usage_summary(db: Session, user: User, settings: Settings) -> UsageSummary:
    now = utcnow()
    start, end = month_bounds(now)
    audio_seconds, jobs = db.execute(
        select(
            func.coalesce(func.sum(UsageEvent.audio_seconds), 0.0),
            func.count(UsageEvent.id),
        ).where(UsageEvent.user_id == user.id, UsageEvent.created_at >= start)
    ).one()
    return UsageSummary(
        plan=user.plan,
        period_start=start,
        period_end=end,
        chars_used=chars_used_this_month(db, user.id, now),
        chars_quota=quota_for(user, settings),
        audio_seconds=round(float(audio_seconds), 2),
        jobs_succeeded=int(jobs),
    )
