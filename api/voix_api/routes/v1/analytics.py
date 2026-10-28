"""Operator analytics, read from the dbt-style views in voix_api/analytics/models."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, bindparam, text

from voix_api.db import utcnow
from voix_api.errors import ApiError
from voix_api.security.deps import DbDep, Principal, PrincipalDep

router = APIRouter(prefix="/analytics", tags=["analytics"])


def require_admin(principal: PrincipalDep) -> Principal:
    if not principal.user.is_admin:
        raise ApiError(403, "forbidden", "Analytics is available to operators only")
    return principal


AdminDep = Annotated[Principal, Depends(require_admin)]


def _rows(db, sql: str, since: date) -> list[dict[str, Any]]:
    stmt = text(sql).bindparams(bindparam("since", type_=Date))
    out = []
    for row in db.execute(stmt, {"since": since}).mappings():
        d = dict(row)
        if isinstance(d.get("day"), date):
            d["day"] = d["day"].isoformat()
        out.append(d)
    return out


def nearest_rank(values: list[float], pct: int) -> float | None:
    """Same definition as the SQL marts: the ceil(n*p)-th smallest value."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(len(ordered) * pct / 100)) - 1]


@router.get("")
def analytics(
    db: DbDep,
    _: AdminDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    """Daily activity and per-engine performance for the last `days` days (admin only)."""
    since = (utcnow() - timedelta(days=days - 1)).date()
    daily = _rows(db, "SELECT * FROM fct_daily_activity WHERE day >= :since ORDER BY day", since)
    engine_daily = _rows(db, "SELECT * FROM fct_engine_daily WHERE day >= :since ORDER BY day, engine", since)
    finished = _rows(
        db,
        "SELECT engine, status, user_id, char_count, processing_ms, queue_ms, audio_seconds, synthesis_rtf "
        "FROM stg_jobs WHERE job_type = 'synthesize' AND is_terminal = 1 AND day >= :since",
        since,
    )
    users = _rows(db, "SELECT COUNT(DISTINCT user_id) AS n FROM stg_jobs WHERE day >= :since", since)[0]["n"]

    engines: dict[str, dict[str, Any]] = {}
    for engine in sorted({r["engine"] for r in finished}):
        rows = [r for r in finished if r["engine"] == engine]
        ok = [r for r in rows if r["status"] == "succeeded"]
        failed = sum(r["status"] == "failed" for r in rows)
        proc = [r["processing_ms"] for r in ok if r["processing_ms"] is not None]
        queue = [r["queue_ms"] for r in rows if r["queue_ms"] is not None]
        rtf = [r["synthesis_rtf"] for r in ok if r["synthesis_rtf"] is not None]
        engines[engine] = {
            "jobs": len(rows),
            "succeeded": len(ok),
            "failed": failed,
            "canceled": len(rows) - len(ok) - failed,
            "failure_rate": failed / (len(ok) + failed) if (ok or failed) else None,
            "chars": sum(r["char_count"] for r in ok),
            "audio_seconds": round(sum(r["audio_seconds"] or 0 for r in ok), 2),
            "p50_processing_ms": nearest_rank(proc, 50),
            "p95_processing_ms": nearest_rank(proc, 95),
            "p50_queue_ms": nearest_rank(queue, 50),
            "p95_queue_ms": nearest_rank(queue, 95),
            "median_synthesis_rtf": nearest_rank(rtf, 50),
        }

    finished_ok = sum(e["succeeded"] for e in engines.values())
    finished_failed = sum(e["failed"] for e in engines.values())
    decided = finished_ok + finished_failed
    return {
        "window": {"since": since.isoformat(), "days": days},
        "totals": {
            "active_users": users,
            "jobs": sum(d["jobs"] for d in daily),
            "chars": sum(e["chars"] for e in engines.values()),
            "audio_seconds": round(sum(e["audio_seconds"] for e in engines.values()), 2),
            "failure_rate": finished_failed / decided if decided else None,
        },
        "engines": engines,
        "daily": daily,
        "engine_daily": engine_daily,
    }
