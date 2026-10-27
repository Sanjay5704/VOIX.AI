"""The worker loop: claim -> run (with lease heartbeats) -> upload -> repeat.

Shutdown (Ctrl+C): the current job is aborted at the next chunk boundary and
*released* back to the queue without spending an attempt, unless it is
already uploading, in which case the upload finishes first. A second Ctrl+C
exits immediately (the lease then expires and the API requeues the job).
"""

from __future__ import annotations

import logging
import shutil
import signal
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from voix_worker import __version__
from voix_worker.client import ApiUnavailable, LeaseLost, WorkerClient
from voix_worker.config import WorkerSettings
from voix_worker.engines.base import Engine, VoiceSpec
from voix_worker.errors import InvalidJobError, JobCanceled, WorkerError
from voix_worker.pipeline.prepare_voice import prepare_reference_clip
from voix_worker.pipeline.synthesize import run_synthesis

logger = logging.getLogger(__name__)


class ShutdownRequested(Exception):
    pass


class _LeaseKeeper(threading.Thread):
    """Heartbeats a running job: extends its lease, reports progress, and
    notices user cancellation or loss of the lease."""

    def __init__(self, client: WorkerClient, job_id: str, interval: float) -> None:
        super().__init__(name=f"lease-{job_id[:8]}", daemon=True)
        self.client = client
        self.job_id = job_id
        self.interval = interval
        self.progress: float | None = 0.0
        self.canceled = threading.Event()
        self.lost = threading.Event()
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.wait(self.interval):
            try:
                resp = self.client.heartbeat(self.job_id, self.progress)
                if resp.get("cancel_requested"):
                    self.canceled.set()
            except LeaseLost:
                self.lost.set()
                return
            except ApiUnavailable as exc:  # keep trying; the lease may still be valid
                logger.warning("job heartbeat failed: %s", exc)

    def stop(self) -> None:
        self._halt.set()


class Worker:
    def __init__(
        self,
        client: WorkerClient,
        engines: dict[str, Engine],
        settings: WorkerSettings,
    ) -> None:
        self.client = client
        self.engines = engines
        self.settings = settings
        self.stop_event = threading.Event()
        self._uploading = False
        self.cache_dir = Path(settings.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # --- lifecycle --------------------------------------------------------------

    def install_signal_handlers(self) -> None:
        def _handle(signum: int, _frame: Any) -> None:
            if self.stop_event.is_set():
                logger.warning("Second interrupt: exiting now")
                raise SystemExit(130)
            logger.info(
                "Shutdown requested; %s", "finishing upload" if self._uploading else "releasing current job"
            )
            self.stop_event.set()

        signal.signal(signal.SIGINT, _handle)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _handle)

    def run_forever(self) -> None:
        self.client.register()
        logger.info(
            "Worker '%s' online: engines=%s api=%s",
            self.client.worker_name,
            list(self.engines),
            self.settings.api_url,
        )
        idle_since = time.monotonic()
        while not self.stop_event.is_set():
            try:
                did_work = self.run_once(wait_seconds=self.settings.poll_wait_seconds)
            except ApiUnavailable as exc:
                logger.error("API unreachable (%s); retrying in 10s", exc)
                self.stop_event.wait(10)
                continue
            if did_work:
                idle_since = time.monotonic()
            elif time.monotonic() - idle_since > 300:
                logger.info("idle; waiting for jobs")
                idle_since = time.monotonic()
        for engine in self.engines.values():
            engine.unload()
        logger.info("Worker stopped")

    def run_once(self, wait_seconds: float = 0.0) -> bool:
        """Claim and process at most one job. Returns True if a job was processed."""
        job = self.client.claim(wait_seconds=wait_seconds)
        if job is None:
            return False
        self.process(job)
        return True

    # --- one job ----------------------------------------------------------------

    def process(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        queue_wait = job.get("created_at")
        logger.info(
            "claimed job %s type=%s engine=%s attempt=%s (enqueued %s)",
            job_id,
            job["type"],
            job["engine"],
            job["attempt"],
            queue_wait,
        )
        keeper = _LeaseKeeper(self.client, job_id, self.settings.heartbeat_interval_seconds)
        keeper.start()

        def check_abort() -> None:
            if keeper.lost.is_set():
                raise LeaseLost(job_id)
            if keeper.canceled.is_set():
                raise JobCanceled("canceled by user")
            if self.stop_event.is_set():
                raise ShutdownRequested()

        def on_progress(p: float) -> None:
            keeper.progress = round(p, 3)

        workdir = Path(tempfile.mkdtemp(prefix=f"voix-{job_id[:8]}-"))
        try:
            if job["type"] == "synthesize":
                result, files = self._synthesize(job, workdir, on_progress, check_abort)
            elif job["type"] == "prepare_voice":
                result, files = self._prepare_voice(job, workdir)
            else:
                raise InvalidJobError(f"Unknown job type {job['type']!r}")
            check_abort()
            self._uploading = True
            status = self.client.complete(job_id, result, files)
            logger.info("job %s -> %s", job_id, status.get("status"))
        except ShutdownRequested:
            logger.info("releasing job %s back to the queue", job_id)
            self._safe(self.client.release, job_id)
        except LeaseLost:
            logger.warning("lost lease on job %s; abandoning it", job_id)
        except JobCanceled:
            logger.info("job %s canceled by user", job_id)
            self._safe(self.client.fail, job_id, "canceled by user", retryable=False)
        except WorkerError as exc:
            logger.error(
                "job %s failed (%s): %s", job_id, "retryable" if exc.retryable else "permanent", exc.message
            )
            self._safe(self.client.fail, job_id, exc.message, retryable=exc.retryable)
        except Exception as exc:  # unexpected -> let the queue retry it
            logger.exception("job %s crashed", job_id)
            self._safe(self.client.fail, job_id, f"{type(exc).__name__}: {exc}", retryable=True)
        finally:
            self._uploading = False
            keeper.stop()
            shutil.rmtree(workdir, ignore_errors=True)

    def _safe(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        try:
            fn(*args, **kwargs)
        except (LeaseLost, ApiUnavailable) as exc:
            logger.warning("could not report job outcome: %s", exc)

    def _engine(self, name: str) -> Engine:
        engine = self.engines.get(name)
        if engine is None:
            raise InvalidJobError(f"This worker does not run engine '{name}'")
        return engine

    def _voice_spec(self, voice: dict[str, Any] | None) -> VoiceSpec:
        if voice is None:
            raise InvalidJobError("Job has no voice")
        reference = None
        if voice.get("reference_url"):
            safe_tag = "".join(c if c.isalnum() or c in "-_" else "_" for c in voice["cache_tag"])
            reference = self.cache_dir / "voices" / f"{safe_tag}.wav"
            if not reference.exists():  # reference clips are immutable per cache_tag
                self.client.download(voice["reference_url"], reference)
        return VoiceSpec(
            voice_id=str(voice["id"]), engine_voice_id=voice.get("engine_voice_id"), reference_wav=reference
        )

    def _synthesize(self, job: dict[str, Any], workdir: Path, on_progress: Any, check_abort: Any):
        engine = self._engine(job["engine"])
        voice = self._voice_spec(job.get("voice"))
        out = run_synthesis(engine, voice, job["params"], workdir, on_progress, check_abort)
        files = {"audio": out.audio_path}
        if out.subtitles_path is not None:
            files["subtitles"] = out.subtitles_path
        out.result["metrics"]["worker_version"] = __version__
        return out.result, files

    def _prepare_voice(self, job: dict[str, Any], workdir: Path):
        voice = job.get("voice") or {}
        if not voice.get("source_url"):
            raise InvalidJobError("Voice has no uploaded source clip")
        ext = job["params"].get("source_ext", ".wav")
        source = self.client.download(voice["source_url"], workdir / f"source{ext}")
        reference = workdir / "reference.wav"
        t0 = time.perf_counter()
        duration = prepare_reference_clip(source, reference)
        result = {
            "duration_seconds": round(duration, 2),
            "metrics": {"processing_ms": int((time.perf_counter() - t0) * 1000)},
        }
        return result, {"reference": reference}
