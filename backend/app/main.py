"""
FastAPI application entrypoint.

Run locally with:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

Or via the provided Dockerfile / docker-compose.yml.
"""

from __future__ import annotations

import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import health_routes, tts_routes, voice_routes
from app.core.config import get_settings
from app.core.exceptions import TTSAppError
from app.core.logging_config import get_logger, setup_logging
from app.services.engines import get_engine, loaded_engines
from app.services.voice_registry import get_voice_registry
from app.utils.file_manager import cleanup_old_outputs

setup_logging()
logger = get_logger(__name__)


def _background_cleanup_loop(interval_seconds: int = 3600) -> None:
    while True:
        time.sleep(interval_seconds)
        try:
            cleanup_old_outputs()
        except Exception:  # noqa: BLE001
            logger.exception("Background cleanup failed")


def _safe_load(engine) -> None:
    try:
        engine.load()
    except Exception:  # noqa: BLE001
        logger.exception("Warm-up load failed; the model will load on first request instead")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting %s v%s (env=%s)", settings.APP_NAME, settings.APP_VERSION, settings.ENVIRONMENT)

    # Warm-load the default voice's engine in a background thread so the server
    # starts accepting requests immediately; other engines load on first use.
    try:
        default_engine, _ = get_voice_registry().resolve(settings.DEFAULT_VOICE)
        engine = get_engine(default_engine.value)
        threading.Thread(target=_safe_load, args=(engine,), daemon=True, name="model-warmup").start()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Skipping model warm-up: %s", exc)

    cleanup_thread = threading.Thread(target=_background_cleanup_loop, daemon=True, name="output-cleanup")
    cleanup_thread.start()

    yield

    logger.info("Shutting down, releasing model resources...")
    for engine in loaded_engines().values():
        engine.unload()


settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Local text-to-speech API with two engines: Kokoro-82M (fast, default) and "
        "Coqui XTTS-v2 (voice cloning). Speed/pitch control, timestamped subtitles, "
        "and batch processing."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(TTSAppError)
async def app_error_handler(request: Request, exc: TTSAppError) -> JSONResponse:
    logger.warning("Handled error [%s]: %s", exc.error_code, exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message, "details": exc.details},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception while processing %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "internal_error",
            "message": "An unexpected error occurred. Please try again or check server logs.",
            "details": {},
        },
    )


app.include_router(health_routes.router)
app.include_router(tts_routes.router)
app.include_router(voice_routes.router)


@app.get("/", tags=["Root"])
def root() -> dict:
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/api/v1/health",
    }
