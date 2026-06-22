"""
API-level tests.

These tests exercise FastAPI routing, request validation, and error
handling WITHOUT loading the actual multi-gigabyte XTTS model, by
monkeypatching the synthesis service. Run with: pytest tests/ -v
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    # Patch model loading before importing the app so lifespan startup
    # doesn't attempt to download/load the real XTTS weights during tests.
    from app.services import tts_engine as tts_engine_module

    class _FakeEngine:
        is_loaded = True

        class device_info:
            device = "cpu"
            gpu_available = False
            gpu_name = None

        def load(self):
            pass

        def unload(self):
            pass

        def synthesize(self, text, speaker_wav, language="en", emotion_exaggeration=1.0):
            sr = 24000
            fake_audio = np.zeros(sr, dtype=np.float32)  # 1 second of silence
            from app.models.schemas import SentenceTimestamp

            timestamps = [SentenceTimestamp(index=0, text=text[:50], start=0.0, end=1.0)]
            return fake_audio, sr, timestamps

    fake_engine = _FakeEngine()
    monkeypatch.setattr(tts_engine_module, "get_engine", lambda: fake_engine)

    from app.utils import voice_assets

    monkeypatch.setattr(voice_assets, "ensure_default_voice_assets", lambda: None)

    from app.main import app

    with TestClient(app) as c:
        yield c


def test_root_endpoint(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "name" in resp.json()


def test_health_endpoint(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["device"] == "cpu"


def test_list_voices_includes_presets(client):
    resp = client.get("/api/v1/voices")
    assert resp.status_code == 200
    voice_ids = {v["voice_id"] for v in resp.json()}
    assert "male" in voice_ids
    assert "female" in voice_ids


def test_generate_rejects_empty_text(client):
    resp = client.post("/api/v1/generate", json={"text": "", "voice_id": "male"})
    assert resp.status_code == 422


def test_generate_rejects_invalid_speed(client):
    resp = client.post(
        "/api/v1/generate", json={"text": "Hello", "voice_id": "male", "speed": 5.0}
    )
    assert resp.status_code == 422


def test_generate_unknown_voice_returns_404(client):
    resp = client.post(
        "/api/v1/generate", json={"text": "Hello world", "voice_id": "nonexistent_voice"}
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "voice_not_found"


def test_audio_not_found_returns_404(client):
    resp = client.get("/api/v1/audio/does-not-exist.wav")
    assert resp.status_code == 404


def test_batch_rejects_empty_items(client):
    resp = client.post("/api/v1/generate/batch", json={"items": []})
    assert resp.status_code == 422
