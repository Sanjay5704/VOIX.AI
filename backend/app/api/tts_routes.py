"""TTS generation endpoints: single generate, batch generate, audio retrieval."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.models.schemas import (
    BatchGenerateRequest,
    BatchGenerateResponse,
    GenerateRequest,
    GenerateResponse,
)
from app.services.batch_service import generate_batch
from app.services.synthesis_service import generate_speech

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["TTS Generation"])


@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="Generate speech from text",
    description=(
        "Synthesizes natural speech from input text using XTTS-v2. "
        "Supports voice selection, speed/pitch control, and SRT subtitle generation."
    ),
)
def generate(request: GenerateRequest) -> GenerateResponse:
    return generate_speech(request)


@router.post(
    "/generate/batch",
    response_model=BatchGenerateResponse,
    summary="Batch-generate speech for multiple text items",
    description="Processes up to MAX_BATCH_ITEMS text items sequentially, isolating per-item failures.",
)
def generate_batch_endpoint(request: BatchGenerateRequest) -> BatchGenerateResponse:
    settings = get_settings()
    if len(request.items) > settings.MAX_BATCH_ITEMS:
        raise HTTPException(
            status_code=422,
            detail=f"Batch size {len(request.items)} exceeds the maximum of {settings.MAX_BATCH_ITEMS}.",
        )
    return generate_batch(request)


@router.get(
    "/audio/{filename}",
    summary="Download a generated audio or subtitle file",
    description="Serves generated .wav, .mp3, or .srt files by filename returned from /generate.",
)
def get_audio(filename: str) -> FileResponse:
    settings = get_settings()

    # Prevent path traversal
    safe_name = Path(filename).name
    file_path = settings.OUTPUTS_DIR / safe_name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File '{safe_name}' not found.")

    media_types = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".srt": "application/x-subrip",
    }
    media_type = media_types.get(file_path.suffix.lower(), "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=safe_name,
    )
