"""
API-level tests.

The real pipeline runs (chunking, ffmpeg post-processing, subtitles, file
download), but the TTS model is replaced by a fake engine that returns tones,
so no model download or GPU is needed. Run with: pytest -v
"""

from __future__ import annotations

import shutil

import numpy as np
import pytest
from app.core.config import get_settings
from app.services import engines as engines_module
from app.services import synthesis_service, voice_registry
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


class FakeEngine:
    """Stands in for Kokoro/XTTS: 0.05 s of tone per character."""

    sample_rate = 24_000
    is_loaded = True

    def __init__(self, name):
        self.name = name
        self.calls = []

    def load(self):
        pass

    def unload(self):
        pass

    def synthesize_chunk(self, text, voice, language, expressiveness=1.0):
        self.calls.append((text, voice))
        n = int(len(text) * 0.05 * self.sample_rate)
        return (0.2 * np.sin(np.arange(n) * 2 * np.pi * 220 / self.sample_rate)).astype(np.float32)


@pytest.fixture()
def fakes(monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(settings, "VOICES_DIR", tmp_path / "voices")
    settings.OUTPUTS_DIR.mkdir()
    settings.VOICES_DIR.mkdir()
    monkeypatch.setattr(voice_registry, "_registry", None)  # fresh registry in the temp dir

    made = {name: FakeEngine(name) for name in ("kokoro", "xtts")}
    monkeypatch.setattr(synthesis_service, "get_engine", lambda name: made[name])
    monkeypatch.setattr(engines_module, "get_engine", lambda name: made[name])
    return made


@pytest.fixture()
def client(fakes):
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_root_endpoint(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "name" in resp.json()


def test_health_lists_engines(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["engines"] == ["kokoro", "xtts"]


def test_voices_cover_both_engines(client):
    voices = {v["voice_id"]: v for v in client.get("/api/v1/voices").json()}
    assert voices["af_heart"]["engine"] == "kokoro"
    assert voices["xtts_ana"]["engine"] == "xtts"


def test_generate_rejects_empty_text(client):
    resp = client.post("/api/v1/generate", json={"text": "", "voice_id": "af_heart"})
    assert resp.status_code == 422


def test_generate_unknown_voice_returns_404(client):
    resp = client.post("/api/v1/generate", json={"text": "Hello", "voice_id": "does_not_exist"})
    assert resp.status_code == 404


def test_generate_with_kokoro_end_to_end(client, fakes):
    resp = client.post(
        "/api/v1/generate",
        json={"text": "Hello there. How are you today?", "voice_id": "af_heart", "output_format": "wav"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["engine"] == "kokoro" and body["real_time_factor"] >= 0
    assert [s["text"] for s in body["sentences"]] == ["Hello there.", "How are you today?"]
    assert fakes["kokoro"].calls[0][1].speaker == "af_heart"

    audio = client.get(body["audio_url"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
    import io

    import soundfile as sf

    data, sr = sf.read(io.BytesIO(audio.content))
    assert sr == 24_000  # loudnorm must not leave the file at 192 kHz

    srt = client.get(body["srt_url"]).content
    assert srt.startswith(b"1\n00:00:00,000") and b"\r\n" not in srt


def test_xtts_studio_voice_uses_builtin_speaker(client, fakes):
    resp = client.post(
        "/api/v1/generate", json={"text": "Hi.", "voice_id": "xtts_ana", "output_format": "mp3"}
    )
    assert resp.status_code == 200
    assert resp.json()["engine"] == "xtts"
    assert fakes["xtts"].calls[0][1].speaker == "Ana Florence"


def test_speed_rescales_subtitles(client):
    text = "One sentence here. And another one after it."
    normal = client.post("/api/v1/generate", json={"text": text, "voice_id": "af_heart"}).json()
    fast = client.post("/api/v1/generate", json={"text": text, "voice_id": "af_heart", "speed": 2.0}).json()
    assert fast["sentences"][-1]["end"] == pytest.approx(normal["sentences"][-1]["end"] / 2, abs=0.01)


def test_punctuation_only_text_is_rejected(client, fakes):
    resp = client.post("/api/v1/generate", json={"text": "... !!! ???", "voice_id": "af_heart"})
    assert resp.status_code >= 400
    assert fakes["kokoro"].calls == []  # never sent to the model


def test_kokoro_only_mode_hides_xtts_and_cloning(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "ENABLED_ENGINES", ["kokoro"])
    monkeypatch.setattr(voice_registry, "_registry", None)
    engines = {v["engine"] for v in client.get("/api/v1/voices").json()}
    assert engines == {"kokoro"}
    resp = client.post(
        "/api/v1/voices/clone", files={"file": ("a.wav", b"RIFF", "audio/wav")}, data={"name": "x"}
    )
    assert resp.status_code >= 400


def test_builtin_voice_cannot_be_deleted(client):
    assert client.delete("/api/v1/voices/af_heart").status_code == 400


def test_audio_download_blocks_path_traversal(client):
    assert client.get("/api/v1/audio/..%2F..%2Fapp%2Fmain.py").status_code == 404
