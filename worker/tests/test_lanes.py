"""Per-engine lanes remove head-of-line blocking: a fast job queued behind a
slow one on another engine finishes first. Uses the real runner and pipeline
(mock engines + ffmpeg) against an in-memory fake of the API queue."""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

import pytest

from voix_worker.config import WorkerSettings
from voix_worker.engines.mock import MockEngine
from voix_worker.runner import Worker, build_lanes, run_lanes

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


class SlowEngine(MockEngine):
    id = "slow"

    def synthesize_chunk(self, text, voice, language, expressiveness=1.0):
        time.sleep(3.0)  # wide margin: a cold first ffmpeg start can take a second on Windows
        return super().synthesize_chunk(text, voice, language, expressiveness)


class FakeQueue:
    """FIFO queue shared by all lanes, like the jobs table."""

    def __init__(self, jobs):
        self.jobs = list(jobs)
        self.lock = threading.Lock()
        self.finished: dict[str, float] = {}
        self.claimed_by: dict[str, str] = {}


class FakeClient:
    def __init__(self, queue: FakeQueue, name: str, engines: list[str]):
        self.queue, self.worker_name, self.engines = queue, name, engines

    def register(self):
        return {}

    def claim(self, wait_seconds=0.0):
        with self.queue.lock:
            for job in self.queue.jobs:
                if job["engine"] in self.engines:
                    self.queue.jobs.remove(job)
                    self.queue.claimed_by[job["id"]] = self.worker_name
                    return job
        time.sleep(0.05)
        return None

    def heartbeat(self, job_id, progress):
        return {"cancel_requested": False}

    def complete(self, job_id, result, files):
        self.queue.finished[job_id] = time.perf_counter()
        return {"status": "succeeded"}

    def fail(self, job_id, error, retryable):
        raise AssertionError(f"job {job_id} failed: {error}")

    def release(self, job_id):
        return {}


def _job(job_id, engine):
    return {
        "id": job_id,
        "type": "synthesize",
        "engine": engine,
        "attempt": 1,
        "created_at": None,
        "params": {"text": "Hello there.", "output_format": "wav", "subtitles": False},
        "voice": {"id": f"v-{engine}", "engine_voice_id": "tone_a", "reference_url": None},
    }


def _run(lanes_mode: str, tmp_path: Path, monkeypatch) -> FakeQueue:
    queue = FakeQueue([_job("slow-1", "slow"), _job("fast-1", "mock")])  # slow job is first in line
    settings = WorkerSettings(lanes=lanes_mode, cache_dir=tmp_path / "cache", heartbeat_interval_seconds=60)
    engines = {"slow": SlowEngine(), "mock": MockEngine()}
    lanes = build_lanes(lambda name, names: FakeClient(queue, name, names), engines, settings, "laptop")
    monkeypatch.setattr(Worker, "install_signal_handlers", lambda self, lanes=None: None)

    def stop_when_done():
        while len(queue.finished) < 2:
            time.sleep(0.05)
        lanes[0].stop_event.set()

    threading.Thread(target=stop_when_done, daemon=True).start()
    run_lanes(lanes)
    return queue


def test_build_lanes_names_and_engines(tmp_path):
    settings = WorkerSettings(cache_dir=tmp_path)
    engines = {"slow": SlowEngine(), "mock": MockEngine()}
    made = []
    lanes = build_lanes(lambda n, e: made.append((n, e)) or n, engines, settings, "laptop")
    assert made == [("laptop:slow", ["slow"]), ("laptop:mock", ["mock"])]
    assert len({id(w.stop_event) for w in lanes}) == 1  # one Ctrl+C stops every lane

    shared = build_lanes(
        lambda n, e: n, engines, WorkerSettings(lanes="shared", cache_dir=tmp_path), "laptop"
    )
    assert len(shared) == 1 and list(shared[0].engines) == ["slow", "mock"]


def test_per_engine_lanes_avoid_head_of_line_blocking(tmp_path, monkeypatch):
    q = _run("per-engine", tmp_path, monkeypatch)
    assert q.finished["fast-1"] < q.finished["slow-1"]
    assert q.claimed_by == {"slow-1": "laptop:slow", "fast-1": "laptop:mock"}


def test_shared_lane_blocks_fast_job_behind_slow_one(tmp_path, monkeypatch):
    q = _run("shared", tmp_path, monkeypatch)
    assert q.finished["slow-1"] < q.finished["fast-1"]  # the old behaviour, kept as an option
