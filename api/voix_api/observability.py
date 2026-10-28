"""Request IDs, structured logging, Prometheus metrics and security headers.

One pure-ASGI middleware does the per-request work (no BaseHTTPMiddleware, so
streaming downloads aren't buffered):

- accepts a sane incoming ``X-Request-ID`` or generates one, exposes it via a
  contextvar (logs, error bodies) and echoes it on the response;
- records ``http_requests_total`` / ``http_request_duration_seconds`` labelled
  by route *template* (``/v1/jobs/{job_id}``), never the raw path, so label
  cardinality stays bounded;
- writes one access-log line per request;
- adds security headers.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

access_log = logging.getLogger("voix_api.access")


def current_request_id() -> str | None:
    return _request_id.get()


# --- logging --------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """One JSON object per line: easy to ship to any log store."""

    RESERVED = set(vars(logging.makeLogRecord({})))

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = current_request_id()
        if rid:
            out["request_id"] = rid
        for key, value in vars(record).items():  # structured extras: logger.info("...", extra={...})
            if key not in self.RESERVED and not key.startswith("_"):
                out[key] = value
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup_logging(fmt: str = "json", level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Our middleware writes the access log (with request ids); silence uvicorn's duplicate.
    logging.getLogger("uvicorn.access").disabled = True


# --- metrics ----------------------------------------------------------------

REGISTRY = CollectorRegistry(auto_describe=True)
HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 25),
    registry=REGISTRY,
)
JOBS_CREATED = Counter("voix_jobs_created_total", "Jobs enqueued", ["type", "engine"], registry=REGISTRY)
JOBS_FINISHED = Counter(
    "voix_jobs_finished_total",
    "Jobs reaching a terminal state",
    ["type", "engine", "status"],
    registry=REGISTRY,
)
JOB_PROCESSING = Histogram(
    "voix_job_processing_seconds",
    "Worker-reported processing time of successful synthesis jobs",
    ["engine"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
    registry=REGISTRY,
)
QUEUE_DEPTH = Gauge("voix_queue_depth", "Queued jobs (sampled at scrape)", ["engine"], registry=REGISTRY)
WORKERS_ONLINE = Gauge("voix_workers_online", "Workers seen recently (sampled at scrape)", registry=REGISTRY)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


# --- middleware ---------------------------------------------------------------

_API_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
]
# JSON API responses never need to load anything; the Swagger UI at /docs does.
_API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        token = _request_id.set(rid)
        start = time.perf_counter()
        status_code = 500
        path = scope["path"]

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode()))
                headers.extend(_API_SECURITY_HEADERS)
                if not path.startswith(_DOCS_PATHS):
                    headers.append(_API_CSP)
                if self.hsts:
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            route = scope.get("route")
            template = getattr(route, "path", None) or "unmatched"
            method = scope["method"]
            if template != "/metrics":
                HTTP_REQUESTS.labels(method, template, str(status_code)).inc()
                HTTP_LATENCY.labels(method, template).observe(elapsed)
            if template not in ("/healthz", "/metrics"):
                access_log.info(
                    "%s %s %s %.1fms",
                    method,
                    path,
                    status_code,
                    elapsed * 1000,
                    extra={
                        "method": method,
                        "route": template,
                        "status": status_code,
                        "ms": round(elapsed * 1000, 1),
                    },
                )
            _request_id.reset(token)
