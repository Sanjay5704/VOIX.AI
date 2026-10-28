"""VOIX control-plane API.

Run locally:  uvicorn voix_api.main:app --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import func, select

from voix_api import __version__, analytics
from voix_api.config import Settings, get_settings
from voix_api.db import init_engine, session_factory
from voix_api.errors import ApiError, install_error_handlers
from voix_api.models import Job, JobStatus
from voix_api.observability import (
    QUEUE_DEPTH,
    WORKERS_ONLINE,
    RequestContextMiddleware,
    render_metrics,
    setup_logging,
)
from voix_api.routes.internal import workers as internal_workers
from voix_api.routes.v1 import analytics as analytics_routes
from voix_api.routes.v1 import api_keys, auth, jobs, system, voices
from voix_api.security.credentials import constant_time_equals
from voix_api.services import queue
from voix_api.services.catalog import seed_system_voices

logger = logging.getLogger("voix_api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_format, settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        engine = init_engine(settings.database_url)
        analytics.build(engine)  # (re)create dbt-style analytics views from analytics/models
        with session_factory()() as db:
            added = seed_system_voices(db, settings.enabled_engines)
        logger.info(
            "VOIX API started (env=%s, seeded %d system voices)",
            settings.environment,
            added,
        )
        yield

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "AI voiceover studio + developer TTS API. "
            "Jobs are queued and rendered by pull-based GPU workers."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # bearer tokens, not cookies
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "X-API-Key", "Idempotency-Key", "Content-Type"],
        expose_headers=["Location", "Retry-After"],
    )
    install_error_handlers(app)
    # Outermost: request id, access log, HTTP metrics and security headers wrap everything (incl. CORS).
    app.add_middleware(RequestContextMiddleware, hsts=settings.environment == "production")

    for router in (
        auth.router,
        api_keys.router,
        voices.router,
        jobs.router,
        system.router,
        analytics_routes.router,
    ):
        app.include_router(router, prefix="/v1")
    app.include_router(internal_workers.router)

    @app.get("/metrics", include_in_schema=False)
    def metrics(authorization: str | None = Header(default=None)) -> Response:
        """Prometheus scrape endpoint. Queue gauges are sampled from the DB per scrape."""
        if settings.metrics_token is not None:
            expected = f"Bearer {settings.metrics_token.get_secret_value()}"
            if not authorization or not constant_time_equals(authorization, expected):
                raise ApiError(401, "unauthorized", "Metrics token required")
        with session_factory()() as db:
            depth = dict(
                db.execute(
                    select(Job.engine, func.count(Job.id))
                    .where(Job.status == JobStatus.queued)
                    .group_by(Job.engine)
                ).all()
            )
            for engine in set(settings.enabled_engines) | set(depth):
                QUEUE_DEPTH.labels(engine).set(depth.get(engine, 0))
            WORKERS_ONLINE.set(len(queue.online_workers(db, settings)))
        body, content_type = render_metrics()
        return Response(body, media_type=content_type)

    @app.get("/healthz", include_in_schema=False)
    def liveness() -> dict[str, str]:
        return {"status": "alive"}

    return app


app = create_app()
