"""Analytics views (dbt-style models) and the admin endpoint."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import text

from voix_api import analytics
from voix_api.db import utcnow
from voix_api.models import Job, JobStatus, JobType, User

from .conftest import make_user, register


def _job(db, user, engine, status, processing_ms=None, queue_s=None, chars=100, audio=None, **kw):
    now = utcnow()
    job = Job(
        user_id=user.id,
        type=JobType.synthesize,
        engine=engine,
        status=status,
        params={"text": "x"},
        char_count=chars,
        created_at=now - timedelta(seconds=queue_s or 0),
        started_at=now if queue_s is not None else None,
        result={"duration_seconds": audio, "metrics": {"processing_ms": processing_ms, "synthesis_rtf": 0.1}}
        if processing_ms is not None
        else None,
        **kw,
    )
    db.add(job)
    return job


def test_models_load_and_order():
    models = analytics.load_models()
    assert set(models) == {"stg_jobs", "fct_engine_daily", "fct_daily_activity"}
    order = analytics.build_order(models)
    assert order.index("stg_jobs") < order.index("fct_engine_daily")
    pg = analytics.render(models["stg_jobs"], "postgresql")
    assert "#>> '{metrics,processing_ms}'" in pg and "{{" not in pg
    assert "json_extract(j.result, '$.metrics.processing_ms')" in analytics.render(
        models["stg_jobs"], "sqlite"
    )


def test_engine_daily_percentiles_and_failure_rate(db):
    user = make_user(db)
    other = make_user(db)
    for ms in (100, 200, 300, 400, 500, 600, 700, 800, 900, 1000):  # nearest-rank p50=500, p95=1000
        _job(db, user, "kokoro", JobStatus.succeeded, processing_ms=ms, queue_s=2, audio=3.0)
    _job(db, other, "kokoro", JobStatus.failed, queue_s=1)
    _job(db, other, "kokoro", JobStatus.canceled)
    _job(db, user, "kokoro", JobStatus.queued)  # not terminal: excluded from the mart
    _job(db, user, "xtts", JobStatus.succeeded, processing_ms=40000, queue_s=60, audio=10.0)
    db.commit()

    rows = {r.engine: r for r in db.execute(text("SELECT * FROM fct_engine_daily")).all()}
    k = rows["kokoro"]
    assert (k.jobs, k.succeeded, k.failed, k.canceled, k.users) == (12, 10, 1, 1, 2)
    assert k.p50_processing_ms == 500 and k.p95_processing_ms == 1000
    assert abs(k.failure_rate - 1 / 11) < 1e-9
    assert abs(k.p50_queue_ms - 2000) < 50  # created 2 s before start
    assert rows["xtts"].p50_processing_ms == 40000

    activity = db.execute(text("SELECT * FROM fct_daily_activity")).one()
    assert activity.active_users == 2 and activity.jobs == 14


def test_analytics_endpoint_requires_admin(client, db, user):
    assert client.get("/v1/analytics", headers=user["headers"]).status_code == 403
    db.get(User, uuid.UUID(user["user"]["id"])).is_admin = True
    db.commit()

    u = db.get(User, uuid.UUID(user["user"]["id"]))
    for ms in (1000, 2000, 3000):
        _job(db, u, "kokoro", JobStatus.succeeded, processing_ms=ms, queue_s=1, audio=5.0)
    _job(db, u, "kokoro", JobStatus.failed, queue_s=1)
    db.commit()

    me = client.get("/v1/auth/me", headers=user["headers"]).json()
    assert me["is_admin"] is True
    data = client.get("/v1/analytics?days=7", headers=user["headers"]).json()
    k = data["engines"]["kokoro"]
    assert (k["jobs"], k["succeeded"], k["failed"]) == (4, 3, 1)
    assert k["p50_processing_ms"] == 2000 and k["p95_processing_ms"] == 3000
    assert data["totals"]["active_users"] == 1 and data["totals"]["audio_seconds"] == 15.0
    assert data["daily"][-1]["day"] == utcnow().date().isoformat()
    assert data["engine_daily"][0]["engine"] == "kokoro"


def test_admin_cli_promotes(db, client, settings, monkeypatch):
    from voix_api import admin

    reg = register(client, email="ops@example.com")
    monkeypatch.setattr(admin, "get_settings", lambda: settings)
    assert admin.main(["promote", "ops@example.com"]) == 0
    assert client.get("/v1/auth/me", headers={"Authorization": f"Bearer {reg['access_token']}"}).json()[
        "is_admin"
    ]
    assert admin.main(["set-plan", "ops@example.com", "enterprise"]) == 1
