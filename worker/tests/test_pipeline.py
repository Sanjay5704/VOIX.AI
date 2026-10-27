"""Pipeline tests with the mock engine: real ffmpeg, no model downloads."""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from voix_worker.audio.subtitles import SentenceTimestamp
from voix_worker.engines.base import VoiceSpec
from voix_worker.engines.mock import MockEngine
from voix_worker.errors import InvalidJobError, JobCanceled
from voix_worker.pipeline.prepare_voice import prepare_reference_clip
from voix_worker.pipeline.synthesize import run_synthesis

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")

VOICE = VoiceSpec(voice_id="v1", engine_voice_id="tone_a")
TEXT = "Hello there. This is a test of the VOIX pipeline! Does it work?"


def test_mock_engine_is_deterministic():
    eng = MockEngine()
    a = eng.synthesize_chunk("hello", VOICE, "en")
    b = eng.synthesize_chunk("hello", VOICE, "en")
    assert a.dtype == np.float32 and np.array_equal(a, b)
    assert np.abs(a).max() <= 1.0


def test_wav_pipeline_outputs_audio_srt_and_metrics(tmp_path):
    progress: list[float] = []
    out = run_synthesis(
        MockEngine(), VOICE, {"text": TEXT, "output_format": "wav"}, tmp_path, on_progress=progress.append
    )
    audio, sr = sf.read(out.audio_path)
    assert sr == 24_000  # loudnorm must not leave the file at 192 kHz
    assert abs(len(audio) / sr - out.result["duration_seconds"]) < 0.05

    sentences = out.result["sentences"]
    assert [s["text"] for s in sentences] == [
        "Hello there.",
        "This is a test of the VOIX pipeline!",
        "Does it work?",
    ]
    assert all(
        b["start"] > a["end"] for a, b in zip(sentences, sentences[1:], strict=False)
    )  # pauses between
    assert out.subtitles_path.read_text(encoding="utf-8").startswith("1\n00:00:00,000 --> ")

    m = out.result["metrics"]
    assert m["chars"] == len(TEXT) and m["chunks"] == 3 and m["engine"] == "mock"
    assert m["rtf"] > 0 and m["processing_ms"] >= m["synthesis_ms"]
    assert progress == sorted(progress) and progress[-1] >= 0.85


def test_speed_rescales_subtitles_and_duration(tmp_path):
    normal = run_synthesis(MockEngine(), VOICE, {"text": TEXT, "output_format": "wav"}, tmp_path / "a")
    fast = run_synthesis(
        MockEngine(), VOICE, {"text": TEXT, "output_format": "wav", "speed": 1.5}, tmp_path / "b"
    )
    ratio = normal.result["duration_seconds"] / fast.result["duration_seconds"]
    assert ratio == pytest.approx(1.5, rel=0.03)
    last_n, last_f = normal.result["sentences"][-1], fast.result["sentences"][-1]
    assert last_f["end"] == pytest.approx(last_n["end"] / 1.5, abs=0.002)


def test_mp3_and_pitch(tmp_path):
    out = run_synthesis(MockEngine(), VOICE, {"text": "Short one.", "pitch_semitones": 3}, tmp_path)
    assert out.audio_path.suffix == ".mp3" and out.audio_path.read_bytes()[:3] in (b"ID3", b"\xff\xfb"[:3])
    assert out.result["format"] == "mp3"


def test_empty_text_is_permanent_error(tmp_path):
    with pytest.raises(InvalidJobError):
        run_synthesis(MockEngine(), VOICE, {"text": "   "}, tmp_path)


def test_abort_check_stops_between_chunks(tmp_path):
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise JobCanceled("stop")

    with pytest.raises(JobCanceled):
        run_synthesis(MockEngine(), VOICE, {"text": TEXT}, tmp_path, check_abort=check)


def test_prepare_reference_clip(tmp_path):
    src = tmp_path / "in.wav"
    sr = 44_100
    t = np.linspace(0, 5, 5 * sr, endpoint=False)
    sf.write(src, np.stack([np.sin(2 * np.pi * 220 * t)] * 2, axis=1) * 0.3, sr)  # 5 s stereo 44.1k
    out = tmp_path / "ref.wav"
    duration = prepare_reference_clip(src, out)
    info = sf.info(out)
    assert info.channels == 1 and info.samplerate == 22_050 and duration == pytest.approx(5.0, abs=0.05)


def test_prepare_rejects_short_and_garbage(tmp_path):
    short = tmp_path / "short.wav"
    sf.write(short, np.zeros(22_050, dtype=np.float32), 22_050)  # 1 s
    with pytest.raises(InvalidJobError, match="at least"):
        prepare_reference_clip(short, tmp_path / "o1.wav")
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"definitely not audio")
    with pytest.raises(InvalidJobError):
        prepare_reference_clip(junk, tmp_path / "o2.wav")


def test_sentence_timestamp_scaled():
    assert SentenceTimestamp(0, "x", 1.5, 3.0).scaled(1.5) == SentenceTimestamp(0, "x", 1.0, 2.0)


def test_ffprobe_available():
    assert subprocess.run(["ffprobe", "-version"], capture_output=True).returncode == 0
