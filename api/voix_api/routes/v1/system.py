"""Usage, health and engine catalogue."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import func, select, text

from voix_api.models import Job, JobStatus
from voix_api.schemas import EngineOut, HealthOut, UsageOut, WorkerOut
from voix_api.security.deps import DbDep, PrincipalDep, SettingsDep
from voix_api.services import limits, queue
from voix_api.services.catalog import ENGINES

router = APIRouter(tags=["system"])


@router.get("/usage", response_model=UsageOut)
def get_usage(db: DbDep, principal: PrincipalDep, settings: SettingsDep) -> UsageOut:
    """Month-to-date usage against the caller's plan quota."""
    s = limits.usage_summary(db, principal.user, settings)
    return UsageOut(
        plan=s.plan,
        period_start=s.period_start,
        period_end=s.period_end,
        chars_used=s.chars_used,
        chars_quota=s.chars_quota,
        chars_remaining=max(0, s.chars_quota - s.chars_used),
        audio_seconds=s.audio_seconds,
        jobs_succeeded=s.jobs_succeeded,
    )


@router.get("/health", response_model=HealthOut)
def health(db: DbDep, settings: SettingsDep, response: Response) -> HealthOut:
    """Public. `degraded` = DB unreachable or no GPU worker online (jobs will wait in the queue)."""
    try:
        db.execute(text("SELECT 1"))
        queue.reap_expired(db)  # lazy reaping also happens here, so stale leases recover without traffic
        workers = queue.online_workers(db, settings)
        depth = db.scalar(select(func.count(Job.id)).where(Job.status == JobStatus.queued)) or 0
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthOut(
            status="degraded",
            database="error",
            workers_online=0,
            workers=[],
            queue_depth=0,
        )
    return HealthOut(
        status="ok" if workers else "degraded",
        database="ok",
        workers_online=len(workers),
        workers=[WorkerOut.model_validate(w) for w in workers],
        queue_depth=int(depth),
    )


@router.get("/engines", response_model=list[EngineOut])
def list_engines(db: DbDep, settings: SettingsDep) -> list[EngineOut]:
    """Enabled engines with licence information and whether a worker serving them is online."""
    online = {e for w in queue.online_workers(db, settings) for e in (w.engines or [])}
    return [
        EngineOut(
            id=info.id,
            name=info.name,
            license=info.license,
            commercial_use=info.commercial_use,
            supports_cloning=info.supports_cloning,
            languages=list(info.languages),
            notes=info.notes,
            online=info.id in online,
        )
        for engine_id, info in ENGINES.items()
        if engine_id in settings.enabled_engines
    ]
