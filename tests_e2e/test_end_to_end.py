"""End to end: API + queue + worker + storage, in one process.

The worker's HTTP client is a FastAPI TestClient, so every worker call goes
through the real /internal routes, auth, queue and storage - only the network
socket is skipped. The mock engine makes it run on any CPU in a few seconds.

Run from the repo root:  pytest tests_e2e
(needs api/requirements.txt + worker/requirements.txt + ffmpeg)
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "api"), str(ROOT / "worker")]

from fastapi.testclient import TestClient  # noqa: E402

from voix_api import analytics  # noqa: E402
from voix_api.config import Settings, get_settings  # noqa: E402
from voix_api.db import Base, init_engine  # noqa: E402
from voix_api.main import create_app  # noqa: E402
from voix_api.services.storage import LocalStorage, get_storage  # noqa: E402
from voix_worker.client import WorkerClient  # noqa: E402
from voix_worker.config import WorkerSettings  # noqa: E402
from voix_worker.engines.mock import MockEngine  # noqa: E402
from voix_worker.runner import Worker  # noqa: E402

TOKEN = "e2e-worker-token"


@pytest.fixture
def stack(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(tmp_path / 'e2e.sqlite3').as_posix()}"
    settings = Settings(
        environment="test",
        database_url=url,
        local_storage_dir=tmp_path / "storage",
        worker_token=TOKEN,
        enabled_engines=["mock"],
        clone_engine="mock",
    )
    engine = init_engine(url)
    with engine.begin() as conn:  # views depend on tables; drop them first (matters on Postgres)
        analytics.drop(conn)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    storage = LocalStorage(settings.local_storage_dir)
    app.dependency_overrides[get_storage] = lambda: storage

    with TestClient(app) as user_http, TestClient(app, headers={"X-Worker-Token": TOKEN}) as worker_http:
        wsettings = WorkerSettings(worker_name="e2e-laptop", engines=["mock"], cache_dir=tmp_path / "cache")
        client = WorkerClient(worker_http, "e2e-laptop", ["mock"], gpu=None, version="e2e")
        worker = Worker(client, {"mock": MockEngine()}, wsettings)
        yield user_http, worker, tmp_path


def _auth(user_http) -> dict:
    reg = user_http.post("/v1/auth/register", json={"email": "e2e@example.com", "password": "e2e password!"})
    assert reg.status_code == 201
    key = user_http.post(
        "/v1/api-keys",
        json={"name": "e2e"},
        headers={"Authorization": f"Bearer {reg.json()['access_token']}"},
    ).json()["key"]
    return {"X-API-Key": key}  # the developer-API path


def test_tts_job_end_to_end(stack):
    user_http, worker, _ = stack
    h = _auth(user_http)
    voice = next(v for v in user_http.get("/v1/voices", headers=h).json() if v["engine"] == "mock")

    text = "Welcome to VOIX. This voiceover was rendered by a pull-based worker! Subtitles included."
    job = user_http.post(
        "/v1/jobs/tts",
        json={"text": text, "voice_id": voice["id"], "speed": 1.25, "output_format": "wav"},
        headers={**h, "Idempotency-Key": "e2e-1"},
    ).json()
    assert job["status"] == "queued"
    assert user_http.get("/v1/health").json()["queue_depth"] == 1

    assert worker.run_once() is True  # claim -> synthesize -> upload
    assert worker.run_once() is False  # queue drained

    done = user_http.get(f"/v1/jobs/{job['id']}", headers=h).json()
    assert done["status"] == "succeeded", done["error"]
    assert done["attempts"] == 1 and done["progress"] == 1.0
    metrics = done["result"]["metrics"]
    assert metrics["engine"] == "mock" and metrics["chunks"] == 3 and metrics["rtf"] > 0

    audio = user_http.get(done["audio_url"], headers=h)
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
    data, sr = sf.read(io.BytesIO(audio.content))
    assert sr == 24_000 and len(data) / sr == pytest.approx(done["result"]["duration_seconds"], abs=0.05)

    srt = user_http.get(done["subtitles_url"], headers=h).text
    assert "Welcome to VOIX." in srt and srt.startswith("1\n00:00:00,000")

    usage = user_http.get("/v1/usage", headers=h).json()
    assert usage["chars_used"] == len(text) and usage["jobs_succeeded"] == 1
    assert usage["audio_seconds"] == pytest.approx(done["result"]["duration_seconds"], abs=0.01)


def test_clone_then_speak_end_to_end(stack):
    user_http, worker, tmp_path = stack
    h = _auth(user_http)

    sr = 44_100
    t = np.linspace(0, 4, 4 * sr, endpoint=False)
    buf = io.BytesIO()
    sf.write(buf, (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32), sr, format="WAV")
    clone = user_http.post(
        "/v1/voices",
        data={
            "name": "Me",
            "consent": "true",
            "consent_statement": "I am the person speaking in this clip and I consent to it being cloned.",
        },
        files={"file": ("me.wav", buf.getvalue(), "audio/wav")},
        headers=h,
    )
    assert clone.status_code == 202, clone.text
    voice_id = clone.json()["voice"]["id"]

    assert worker.run_once() is True  # prepare_voice
    voice = user_http.get(f"/v1/voices/{voice_id}", headers=h).json()
    assert voice["status"] == "ready" and voice["duration_seconds"] == pytest.approx(4.0, abs=0.1)

    job = user_http.post(
        "/v1/jobs/tts", json={"text": "Now in my own voice.", "voice_id": voice_id}, headers=h
    ).json()
    assert worker.run_once() is True
    assert user_http.get(f"/v1/jobs/{job['id']}", headers=h).json()["status"] == "succeeded"
    # The standardised reference clip was downloaded once and cached locally.
    assert len(list((tmp_path / "cache" / "voices").glob("*.wav"))) == 1


def test_bad_clip_fails_voice_permanently(stack):
    user_http, worker, _ = stack
    h = _auth(user_http)
    clone = user_http.post(
        "/v1/voices",
        data={
            "name": "Junk",
            "consent": "true",
            "consent_statement": "I am the speaker and I consent to this.",
        },
        files={"file": ("junk.mp3", b"not audio at all", "audio/mpeg")},
        headers=h,
    ).json()
    assert worker.run_once() is True
    voice = user_http.get(f"/v1/voices/{clone['voice']['id']}", headers=h).json()
    assert voice["status"] == "failed" and "decode" in voice["error"]
    job = user_http.get(f"/v1/jobs/{clone['job_id']}", headers=h).json()
    assert job["status"] == "failed" and job["attempts"] == 1  # permanent: not retried
