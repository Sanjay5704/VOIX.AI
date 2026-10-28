"""Health check / readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.models.schemas import HealthResponse
from app.services.device_manager import detect_device
from app.services.engines import loaded_engines

router = APIRouter(prefix="/api/v1", tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health and device status",
)
def health() -> HealthResponse:
    settings = get_settings()
    info = detect_device()
    return HealthResponse(
        status="ok",
        device=info.device,
        gpu_available=info.gpu_available,
        gpu_name=info.gpu_name,
        engines=settings.ENABLED_ENGINES,
        loaded_engines=[name for name, e in loaded_engines().items() if e.is_loaded],
        version=settings.APP_VERSION,
    )
