from __future__ import annotations

import io
import json
import uuid

from sqlalchemy import select

from voix_api.models import AuditLog, Job, JobStatus, Voice, VoiceStatus

from .conftest import register, voice_id


def _tts(client, headers, voice, text="Hello world. This is VOIX.", **extra):
    return client.post("/v1/jobs/tts", json={"text": text, "voice_id": voice, **extra}, headers=headers)


def test_create_job_is_async_202(client, user):
    resp = _tts(client, user["headers"], voice_id(client, user["headers"]))
    assert resp.status_code == 202
    job = resp.json()
    assert job["status"] == "queued" and job["engine"] == "mock" and job["char_count"] == 26
    assert resp.headers["Location"] == f"/v1/jobs/{job['id']}"
    assert job["audio_url"] is None


def test_validation(client, user):
    v = voice_id(client, user["headers"])
    assert _tts(client, user["headers"], v, text="   ").status_code == 422
    assert _tts(client, user["headers"], v, speed=3).status_code == 422
    assert _tts(client, user["headers"], v, text="x" * 5001).status_code == 413
    unknown = _tts(client, user["headers"], "00000000-0000-0000-0000-000000000000")
    assert unknown.status_code == 404


def test_idempotency_replay_and_conflict(client, user):
    v = voice_id(client, user["headers"])
    headers = {**user["headers"], "Idempotency-Key": "abc-123"}
    first = _tts(client, headers, v)
    again = _tts(client, headers, v)
    assert first.status_code == 202 and again.status_code == 200
    assert first.json()["id"] == again.json()["id"]

    conflict = _tts(client, headers, v, text="Different body")
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"

    # Keys are scoped per user.
    other = register(client)
    other_headers = {"Authorization": f"Bearer {other['access_token']}", "Idempotency-Key": "abc-123"}
    assert _tts(client, other_headers, v).status_code == 202


def test_quota_enforced_and_released_on_cancel(client, user, settings):
    settings.plan_quotas = {"free": 100, "pro": 1000}
    v = voice_id(client, user["headers"])
    first = _tts(client, user["headers"], v, text="a" * 60)
    assert first.status_code == 202
    over = _tts(client, user["headers"], v, text="b" * 41)
    assert over.status_code == 402
    assert over.json()["error"]["details"] == {"used": 60, "requested": 41, "quota": 100, "plan": "free"}

    usage = client.get("/v1/usage", headers=user["headers"]).json()
    assert usage["chars_used"] == 60 and usage["chars_remaining"] == 40
    assert usage["limits"] == {"max_text_chars": 5000, "max_upload_mb": 20, "rate_limit_jobs_per_minute": 100}

    # Canceling a queued job releases its reservation.
    assert (
        client.post(f"/v1/jobs/{first.json()['id']}/cancel", headers=user["headers"]).json()["status"]
        == "canceled"
    )
    assert _tts(client, user["headers"], v, text="b" * 41).status_code == 202


def test_rate_limit(client, user, settings):
    settings.rate_limit_jobs_per_minute = 3
    v = voice_id(client, user["headers"])
    for _ in range(3):
        assert _tts(client, user["headers"], v).status_code == 202
    limited = _tts(client, user["headers"], v)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    # Another user is unaffected.
    other = register(client)
    assert _tts(client, {"Authorization": f"Bearer {other['access_token']}"}, v).status_code == 202


def test_list_pagination_and_isolation(client, user):
    v = voice_id(client, user["headers"])
    ids = [_tts(client, user["headers"], v, text=f"Job number {i}.").json()["id"] for i in range(5)]

    seen, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = client.get("/v1/jobs", params=params, headers=user["headers"]).json()
        seen += [j["id"] for j in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == list(reversed(ids))  # newest first, no gaps or duplicates

    other = register(client)
    other_h = {"Authorization": f"Bearer {other['access_token']}"}
    assert client.get("/v1/jobs", headers=other_h).json()["items"] == []
    assert client.get(f"/v1/jobs/{ids[0]}", headers=other_h).status_code == 404
    assert client.get(f"/v1/jobs/{ids[0]}/audio", headers=other_h).status_code == 404


def test_download_before_completion_is_409(client, user):
    job = _tts(client, user["headers"], voice_id(client, user["headers"])).json()
    assert client.get(f"/v1/jobs/{job['id']}/audio", headers=user["headers"]).status_code == 409


def test_api_key_can_create_jobs(client, user):
    key = client.post("/v1/api-keys", json={"name": "sdk"}, headers=user["headers"]).json()["key"]
    resp = _tts(client, {"X-API-Key": key}, voice_id(client, user["headers"]))
    assert resp.status_code == 202


def test_voice_listing_and_engines(client, user):
    voices = client.get("/v1/voices", headers=user["headers"]).json()
    assert {v["engine"] for v in voices} == {"mock", "kokoro", "xtts"}
    assert all(v["is_system"] and v["status"] == "ready" for v in voices)

    engines = {e["id"]: e for e in client.get("/v1/engines").json()}
    assert engines["kokoro"]["commercial_use"] is True and engines["kokoro"]["license"] == "Apache-2.0"
    assert engines["xtts"]["commercial_use"] is False and engines["xtts"]["supports_cloning"] is True


def test_clone_requires_consent(client, user):
    files = {"file": ("me.wav", io.BytesIO(b"RIFF....WAVEfmt "), "audio/wav")}
    no_consent = client.post(
        "/v1/voices",
        data={"name": "Me", "consent": "false", "consent_statement": "I am the speaker and I consent."},
        files=files,
        headers=user["headers"],
    )
    assert no_consent.status_code == 400 and no_consent.json()["error"]["code"] == "consent_required"
    short = client.post(
        "/v1/voices",
        data={"name": "Me", "consent": "true", "consent_statement": "ok"},
        files={"file": ("me.wav", io.BytesIO(b"abc"), "audio/wav")},
        headers=user["headers"],
    )
    assert short.status_code == 400


def test_clone_creates_pending_voice_job_and_audit(client, db, user, settings):
    statement = "I am the speaker in this recording and I consent to cloning my voice."
    resp = client.post(
        "/v1/voices",
        data={"name": "My voice", "consent": "true", "consent_statement": statement},
        files={"file": ("me.mp3", io.BytesIO(b"fake mp3 bytes"), "audio/mpeg")},
        headers=user["headers"],
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["voice"]["status"] == "pending" and body["voice"]["is_system"] is False

    voice = db.get(Voice, uuid.UUID(body["voice"]["id"]))
    assert voice.consent_statement == statement and voice.consent_ip and voice.consent_at
    assert (settings.local_storage_dir / voice.source_key).read_bytes() == b"fake mp3 bytes"
    job = db.get(Job, uuid.UUID(body["job_id"]))
    assert job.type.value == "prepare_voice" and job.status == JobStatus.queued

    audit = db.scalar(select(AuditLog).where(AuditLog.action == "voice.clone_consent"))
    assert audit.target == str(voice.id) and audit.meta["statement"] == statement

    # Not usable until prepared; invisible to other users.
    assert _tts(client, user["headers"], str(voice.id)).status_code == 409
    other = register(client)
    assert (
        client.get(
            f"/v1/voices/{voice.id}", headers={"Authorization": f"Bearer {other['access_token']}"}
        ).status_code
        == 404
    )


def test_clone_rejects_oversize_and_bad_type(client, user, settings):
    settings.max_upload_mb = 1
    data = {"name": "Big", "consent": "true", "consent_statement": "I am the speaker and I consent fully."}
    big = client.post(
        "/v1/voices", data=data, files={"file": ("a.wav", io.BytesIO(b"0" * (1024 * 1024 + 1)), "audio/wav")},
        headers=user["headers"],
    )  # fmt: skip
    assert big.status_code == 413
    exe = client.post(
        "/v1/voices", data=data, files={"file": ("a.exe", io.BytesIO(b"MZ"), "x")}, headers=user["headers"]
    )
    assert exe.status_code == 415


def test_system_voice_cannot_be_deleted(client, user):
    v = voice_id(client, user["headers"])
    assert client.delete(f"/v1/voices/{v}", headers=user["headers"]).status_code == 403


def test_health_reports_no_workers(client):
    health = client.get("/v1/health").json()
    assert health["database"] == "ok" and health["workers_online"] == 0 and health["status"] == "degraded"


def test_error_envelope_shape(client):
    resp = client.get("/v1/jobs")
    assert resp.status_code == 401
    assert set(resp.json()["error"]) == {"code", "message", "details"}
    assert json.loads(resp.text)["error"]["code"] == "unauthorized"


def test_ready_voice_flag(db, client, user):
    # sanity: seeded system voices are ready
    assert db.scalar(select(Voice).where(Voice.engine == "mock")).status == VoiceStatus.ready
