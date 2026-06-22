"""Voice management endpoints: list voices, clone voice, delete cloned voice."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.logging_config import get_logger
from app.models.schemas import CloneVoiceResponse, VoiceInfo
from app.services.voice_cloning_service import clone_voice_from_upload
from app.services.voice_registry import get_voice_registry

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/voices", tags=["Voice Management"])


@router.get(
    "",
    response_model=list[VoiceInfo],
    summary="List all available voices",
    description="Returns built-in presets (Male, Female) plus any cloned custom voices.",
)
def list_voices() -> list[VoiceInfo]:
    registry = get_voice_registry()
    return registry.list_voices()


@router.get(
    "/{voice_id}",
    response_model=VoiceInfo,
    summary="Get details for a specific voice",
)
def get_voice(voice_id: str) -> VoiceInfo:
    registry = get_voice_registry()
    return registry.get_voice(voice_id)


@router.post(
    "/clone",
    response_model=CloneVoiceResponse,
    summary="Clone a new voice from an uploaded audio sample",
    description=(
        "Upload a 3-60 second clean speech sample (wav/mp3/flac/ogg/m4a). "
        "Returns a new voice_id usable in /generate requests."
    ),
)
async def clone_voice(
    file: UploadFile = File(..., description="Reference audio sample"),
    name: str = Form(default="", description="Display name for the cloned voice"),
) -> CloneVoiceResponse:
    if not file.filename:
        raise HTTPException(status_code=422, detail="Uploaded file must have a filename.")
    file_bytes = await file.read()
    return clone_voice_from_upload(file_bytes, file.filename, name)


@router.delete(
    "/{voice_id}",
    summary="Delete a cloned voice",
    description="Removes a custom cloned voice. Built-in presets (male/female) cannot be deleted.",
)
def delete_voice(voice_id: str) -> dict:
    if voice_id in {"male", "female"}:
        raise HTTPException(status_code=400, detail="Built-in voices cannot be deleted.")
    registry = get_voice_registry()
    registry.delete_cloned_voice(voice_id)
    return {"message": f"Voice '{voice_id}' deleted."}
