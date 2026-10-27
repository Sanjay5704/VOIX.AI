"""Queue semantics: claim, lease, heartbeat, reap, retry, cancel - at the
service layer and through the internal worker API."""

from __future__ import annotations

import io
import json
import threading
from datetime import timedelta

import pytest
from sqlalchemy import select

from voix_api.db import session_factory, utcnow
from voix_api.models import Job, JobStatus, JobType, UsageEvent
from voix_api.services import queue

from .conftest import make_user


def _enqueue(db, user, engine="mock", priority=0, max_attempts=3, **kw) -> Job:
    job = Job(
        user_id=user.id,
        type=JobType.synthesize,
        engine=engine,
        params={"text": "hi"},
        char_count=2,
        priority=priority,
        max_attempts=max_attempts,
        **kw,
    )
    db.add(job)
    db.commit()
    return job


def test_claim_order_priority_then_fifo_and_engine_filter(db, settings):
    user = make_user(db)
    t0 = utcnow()
    low = _enqueue(db, user, created_at=t0)
    other_engine = _enqueue(db, user, engine="xtts", priority=99, created_at=t0 + timedelta(seconds=1))
    high = _enqueue(db, user, priority=10, created_at=t0 + timedelta(seconds=2))
    low2 = _enqueue(db, user, created_at=t0 + timedelta(seconds=3))
    worker = queue.touch_worker(db, "w1", ["mock"])
    db.commit()

    claimed = [queue.claim(db, worker, ["mock"], settings).id for _ in range(3)]
    assert claimed == [high.id, low.id, low2.id]
    assert queue.claim(db, worker, ["mock"], settings) is None
    db.refresh(other_engine)
    assert other_engine.status == JobStatus.queued  # never handed to a mock-only worker


def test_claim_sets_lease_and_attempt(db, settings):
    user = make_user(db)
    _enqueue(db, user)
    worker = queue.touch_worker(db, "w1", ["mock"])
    job = queue.claim(db, worker, ["mock"], settings)
    assert job.status == JobStatus.running and job.attempts == 1 and job.worker_id == worker.id
    assert timedelta(seconds=55) < job.lease_expires_at - utcnow() <= timedelta(seconds=60)


def test_heartbeat_extends_lease_and_rejects_non_owner(db, settings):
    user = make_user(db)
    _enqueue(db, user)
    w1 = queue.touch_worker(db, "w1", ["mock"])
    w2 = queue.touch_worker(db, "w2", ["mock"])
    job = queue.claim(db, w1, ["mock"], settings)
    job.lease_expires_at = utcnow() + timedelta(seconds=5)
    db.commit()

    job = queue.heartbeat(db, job.id, w1, 0.5, settings)
    assert job.lease_expires_at - utcnow() > timedelta(seconds=50) and job.progress == 0.5
    with pytest.raises(queue.LeaseLost):
        queue.heartbeat(db, job.id, w2, 0.6, settings)


def test_expired_lease_is_requeued_then_failed_after_max_attempts(db, settings):
    user = make_user(db)
    job = _enqueue(db, user, max_attempts=2)
    worker = queue.touch_worker(db, "w1", ["mock"])

    for attempt in (1, 2):
        claimed = queue.claim(db, worker, ["mock"], settings)
        assert claimed.id == job.id and claimed.attempts == attempt
        claimed.lease_expires_at = utcnow() - timedelta(seconds=1)  # worker vanished
        db.commit()
        result = queue.reap_expired(db)
        db.refresh(job)
        if attempt == 1:
            assert result.requeued == 1 and job.status == JobStatus.queued and "lease expired" in job.error
        else:
            assert result.failed == 1 and job.status == JobStatus.failed and job.finished_at


def test_stale_owner_cannot_complete_after_reap(db, settings):
    user = make_user(db)
    job = _enqueue(db, user)
    w1 = queue.touch_worker(db, "w1", ["mock"])
    w2 = queue.touch_worker(db, "w2", ["mock"])
    queue.claim(db, w1, ["mock"], settings)
    db.get(Job, job.id).lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert queue.claim(db, w2, ["mock"], settings).id == job.id  # reaped + reclaimed
    with pytest.raises(queue.LeaseLost):
        queue.complete(db, job.id, w1, {"format": "mp3"})


def test_retryable_failure_backs_off_permanent_fails(db, settings):
    settings.retry_backoff_seconds = 30
    user = make_user(db)
    job = _enqueue(db, user)
    worker = queue.touch_worker(db, "w1", ["mock"])

    queue.claim(db, worker, ["mock"], settings)
    queue.fail(db, job.id, worker, "CUDA OOM", retryable=True, settings=settings)
    db.refresh(job)
    assert job.status == JobStatus.queued and job.run_after > utcnow() + timedelta(seconds=25)
    assert queue.claim(db, worker, ["mock"], settings) is None  # still backing off

    job.run_after = None
    db.commit()
    queue.claim(db, worker, ["mock"], settings)
    queue.fail(db, job.id, worker, "bad voice", retryable=False, settings=settings)
    db.refresh(job)
    assert job.status == JobStatus.failed and job.error == "bad voice"


def test_release_does_not_spend_an_attempt(db, settings):
    user = make_user(db)
    job = _enqueue(db, user)
    worker = queue.touch_worker(db, "w1", ["mock"])
    queue.claim(db, worker, ["mock"], settings)
    queue.release(db, job.id, worker)
    db.refresh(job)
    assert job.status == JobStatus.queued and job.attempts == 0


def test_cancel_running_job_is_cooperative(db, settings):
    user = make_user(db)
    job = _enqueue(db, user)
    worker = queue.touch_worker(db, "w1", ["mock"])
    queue.claim(db, worker, ["mock"], settings)
    queue.request_cancel(db, db.get(Job, job.id))
    hb = queue.heartbeat(db, job.id, worker, 0.3, settings)
    assert hb.cancel_requested and hb.status == JobStatus.running
    queue.fail(db, job.id, worker, "canceled by user", retryable=False, settings=settings)
    db.refresh(job)
    assert job.status == JobStatus.canceled


def test_complete_records_usage_event(db, settings):
    user = make_user(db)
    job = _enqueue(db, user)
    worker = queue.touch_worker(db, "w1", ["mock"])
    queue.claim(db, worker, ["mock"], settings)
    queue.complete(db, job.id, worker, {"format": "mp3"}, {"audio_seconds": 3.5, "processing_ms": 1200})
    event = db.scalar(select(UsageEvent).where(UsageEvent.job_id == job.id))
    assert (
        event.chars == 2
        and event.audio_seconds == 3.5
        and event.processing_ms == 1200
        and event.queue_ms >= 0
    )


def test_concurrent_claims_never_double_claim(client, settings):
    """Many threads, each its own session/connection, racing for jobs.
    Meaningful on Postgres (FOR UPDATE SKIP LOCKED); SQLite serialises writers."""
    with session_factory()() as db:
        user = make_user(db)
        jobs = [_enqueue(db, user).id for _ in range(20)]

    claimed: list = []
    errors: list = []
    lock = threading.Lock()

    def worker_loop(n: int) -> None:
        try:
            with session_factory()() as db:
                worker = queue.touch_worker(db, f"w{n}", ["mock"])
                db.commit()
                while True:
                    job = queue.claim(db, worker, ["mock"], settings)
                    if job is None:
                        return
                    with lock:
                        claimed.append(job.id)
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    is_sqlite = settings.database_url.startswith("sqlite")
    threads = [threading.Thread(target=worker_loop, args=(i,)) for i in range(1 if is_sqlite else 6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors
    assert sorted(claimed) == sorted(jobs)  # every job exactly once


# --- through the HTTP worker API ------------------------------------------------


def test_worker_api_full_cycle(client, user, worker_headers, settings):
    voices = client.get("/v1/voices", headers=user["headers"]).json()
    v = next(x["id"] for x in voices if x["engine"] == "mock")
    job = client.post(
        "/v1/jobs/tts", json={"text": "Hello there.", "voice_id": v}, headers=user["headers"]
    ).json()

    hello = {"worker_name": "laptop", "engines": ["mock"], "gpu": "RTX 4070 Laptop", "version": "test"}
    assert (
        client.post(
            "/internal/jobs/claim", json={**hello, "engines": ["xtts"]}, headers=worker_headers
        ).status_code
        == 204
    )
    claim = client.post("/internal/jobs/claim", json=hello, headers=worker_headers)
    assert claim.status_code == 200
    claimed = claim.json()
    assert claimed["id"] == job["id"] and claimed["voice"]["engine_voice_id"] == "tone_a"
    assert claimed["params"]["text"] == "Hello there."

    health = client.get("/v1/health").json()
    assert health["workers_online"] == 1 and health["status"] == "ok"
    assert health["workers"][0]["gpu"] == "RTX 4070 Laptop"

    hb = client.post(
        f"/internal/jobs/{job['id']}/heartbeat",
        json={"worker_name": "laptop", "progress": 0.5},
        headers=worker_headers,
    )
    assert hb.status_code == 200 and hb.json()["cancel_requested"] is False
    assert client.get(f"/v1/jobs/{job['id']}", headers=user["headers"]).json()["progress"] == 0.5

    # Someone else's worker can't touch it.
    other = client.post(
        f"/internal/jobs/{job['id']}/heartbeat", json={"worker_name": "intruder"}, headers=worker_headers
    )
    assert other.status_code == 409

    result = {
        "format": "mp3",
        "duration_seconds": 1.2,
        "sample_rate": 24000,
        "sentences": [],
        "metrics": {"processing_ms": 900},
    }
    done = client.post(
        f"/internal/jobs/{job['id']}/complete",
        data={"worker_name": "laptop", "result": json.dumps(result)},
        files={"audio": ("output.mp3", io.BytesIO(b"ID3fakeaudio"), "audio/mpeg"), "subtitles": ("s.srt", io.BytesIO(b"1\n"), "text/plain")},
        headers=worker_headers,
    )  # fmt: skip
    assert done.status_code == 200 and done.json()["status"] == "succeeded"

    final = client.get(f"/v1/jobs/{job['id']}", headers=user["headers"]).json()
    assert final["audio_url"] == f"/v1/jobs/{job['id']}/audio" and final["subtitles_url"]
    assert "audio_key" not in final["result"]  # storage keys never leak to clients
    audio = client.get(final["audio_url"], headers=user["headers"])
    assert audio.status_code == 200 and audio.content == b"ID3fakeaudio"
    assert audio.headers["content-type"] == "audio/mpeg"

    usage = client.get("/v1/usage", headers=user["headers"]).json()
    assert usage["jobs_succeeded"] == 1 and usage["audio_seconds"] == 1.2
