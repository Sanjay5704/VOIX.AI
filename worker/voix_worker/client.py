"""HTTP client for the API's /internal endpoints.

Every call retries transient failures (connection errors, timeouts, 5xx,
429) with exponential backoff + jitter, so a flaky home connection or an
API cold start doesn't fail jobs. A 409 means we lost the job's lease and
is surfaced as `LeaseLost` rather than retried.
"""

from __future__ import annotations

import json
import logging
import random
import time
import uuid
from pathlib import Path
from typing import Any, BinaryIO

import httpx

logger = logging.getLogger(__name__)

_RETRY_STATUS = {429, 500, 502, 503, 504}


class LeaseLost(Exception):
    pass


class ApiUnavailable(Exception):
    pass


class WorkerClient:
    def __init__(
        self,
        http: httpx.Client,
        worker_name: str,
        engines: list[str],
        gpu: str | None = None,
        version: str | None = None,
        max_retries: int = 5,
        backoff_base: float = 0.5,
        backoff_cap: float = 30.0,
    ) -> None:
        self.http = http
        self.worker_name = worker_name
        self.engines = engines
        self.gpu = gpu
        self.version = version
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap

    @classmethod
    def create(cls, api_url: str, token: str, timeout: float, **kwargs: Any) -> WorkerClient:
        http = httpx.Client(
            base_url=api_url.rstrip("/"),
            headers={"X-Worker-Token": token, "User-Agent": "voix-worker"},
            timeout=httpx.Timeout(timeout, connect=10.0),
            follow_redirects=True,  # S3 storage answers downloads with presigned redirects
        )
        return cls(http, **kwargs)

    # --- transport ------------------------------------------------------------

    def _request(self, method: str, url: str, *, retry: bool = True, **kwargs: Any) -> httpx.Response:
        attempt = 0
        while True:
            try:
                resp = self.http.request(method, url, **kwargs)
                if resp.status_code == 409:
                    raise LeaseLost(resp.text)
                if resp.status_code not in _RETRY_STATUS or not retry:
                    resp.raise_for_status()
                    return resp
                problem = f"HTTP {resp.status_code}"
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if not retry:
                    raise ApiUnavailable(str(exc)) from exc
                problem = f"{type(exc).__name__}: {exc}"

            attempt += 1
            if attempt > self.max_retries:
                raise ApiUnavailable(f"{method} {url} failed after {self.max_retries} retries ({problem})")
            delay = min(self.backoff_cap, self.backoff_base * 2 ** (attempt - 1)) * random.uniform(0.5, 1.0)
            logger.warning(
                "%s %s -> %s; retry %d/%d in %.1fs", method, url, problem, attempt, self.max_retries, delay
            )
            # Files must be rewound before resending a multipart body.
            for f in (kwargs.get("files") or {}).values():
                f[1].seek(0)
            time.sleep(delay)

    def _hello(self) -> dict[str, Any]:
        return {
            "worker_name": self.worker_name,
            "engines": self.engines,
            "gpu": self.gpu,
            "version": self.version,
        }

    # --- API ----------------------------------------------------------------

    def register(self) -> dict[str, Any]:
        return self._request("POST", "/internal/workers/heartbeat", json=self._hello()).json()

    def claim(self, wait_seconds: float = 0.0) -> dict[str, Any] | None:
        resp = self._request(
            "POST", "/internal/jobs/claim", json={**self._hello(), "wait_seconds": wait_seconds}
        )
        return None if resp.status_code == 204 else resp.json()

    def heartbeat(self, job_id: uuid.UUID | str, progress: float | None) -> dict[str, Any]:
        body = {"worker_name": self.worker_name, "progress": progress}
        return self._request("POST", f"/internal/jobs/{job_id}/heartbeat", json=body).json()

    def complete(
        self, job_id: uuid.UUID | str, result: dict[str, Any], files: dict[str, Path]
    ) -> dict[str, Any]:
        handles: dict[str, tuple[str, BinaryIO, str]] = {}
        try:
            for field, path in files.items():
                handles[field] = (path.name, path.open("rb"), "application/octet-stream")
            data = {"worker_name": self.worker_name, "result": json.dumps(result)}
            return self._request("POST", f"/internal/jobs/{job_id}/complete", data=data, files=handles).json()
        finally:
            for _, fh, _ in handles.values():
                fh.close()

    def fail(self, job_id: uuid.UUID | str, error: str, retryable: bool) -> dict[str, Any]:
        body = {"worker_name": self.worker_name, "error": error[:4000], "retryable": retryable}
        return self._request("POST", f"/internal/jobs/{job_id}/fail", json=body).json()

    def release(self, job_id: uuid.UUID | str) -> dict[str, Any]:
        return self._request(
            "POST", f"/internal/jobs/{job_id}/release", json={"worker_name": self.worker_name}
        ).json()

    def download(self, url: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        resp = self._request("GET", url)
        tmp.write_bytes(resp.content)
        tmp.replace(dest)
        return dest
