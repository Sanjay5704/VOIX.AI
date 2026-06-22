"""Health check / readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.models.schemas import HealthResponse
from app.services.tts_engine import get_engine

router = APIRouter(prefix="/api/v1", tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health and device status",
)
def health() -> HealthResponse:
    settings = get_settings()
    engine = get_engine()
    info = engine.device_info
    return HealthResponse(
        status="ok",
        device=info.device,
        model_loaded=engine.is_loaded,
        gpu_available=info.gpu_available,
        gpu_name=info.gpu_name,
        version=settings.APP_VERSION,
    )
