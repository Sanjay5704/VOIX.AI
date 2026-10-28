"""Pydantic request/response schemas for the TTS API."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class VoiceGender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    CUSTOM = "custom"


class EngineName(str, Enum):
    KOKORO = "kokoro"
    XTTS = "xtts"


class AudioFormat(str, Enum):
    WAV = "wav"
    MP3 = "mp3"


class VoiceInfo(BaseModel):
    voice_id: str
    name: str
    gender: VoiceGender
    description: str = ""
    is_custom: bool = False
    preview_url: Optional[str] = None
    # Older registry files have no engine field: cloned voices were always XTTS.
    engine: EngineName = EngineName.XTTS
    language: str = "en"


class SentenceTimestamp(BaseModel):
    index: int
    text: str
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")


class GenerateRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to synthesize")
    voice_id: str = Field(default="af_heart", description="Voice id from GET /api/v1/voices")
    language: str = Field(default="en", description="ISO language code, e.g. 'en', 'es', 'hi'")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Playback speed multiplier")
    pitch_semitones: float = Field(default=0.0, ge=-12.0, le=12.0, description="Pitch shift in semitones")
    output_format: AudioFormat = Field(default=AudioFormat.WAV)
    generate_subtitles: bool = Field(default=True, description="Generate .srt subtitle file")
    emotion_exaggeration: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Prosody intensity multiplier (1.0 = natural, neutral baseline)",
    )

    @field_validator("text")
    @classmethod
    def strip_text(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text must not be empty")
        return v


class BatchGenerateItem(BaseModel):
    id: str = Field(..., description="Caller-supplied identifier for this item")
    text: str = Field(..., min_length=1)
    voice_id: str = Field(default="af_heart")
    language: str = Field(default="en")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch_semitones: float = Field(default=0.0, ge=-12.0, le=12.0)
    output_format: AudioFormat = Field(default=AudioFormat.WAV)


class BatchGenerateRequest(BaseModel):
    items: List[BatchGenerateItem] = Field(..., min_length=1)
    generate_subtitles: bool = Field(default=True)


class GenerateResponse(BaseModel):
    job_id: str
    voice_id: str
    engine: EngineName
    language: str
    duration_seconds: float
    audio_url: str
    srt_url: Optional[str] = None
    format: AudioFormat
    sample_rate: int
    sentences: List[SentenceTimestamp] = Field(default_factory=list)
    processing_time_seconds: float
    real_time_factor: float = Field(
        description="Synthesis time / audio length. Below 1 means faster than real time."
    )


class BatchGenerateResultItem(BaseModel):
    id: str
    success: bool
    result: Optional[GenerateResponse] = None
    error: Optional[str] = None


class BatchGenerateResponse(BaseModel):
    batch_id: str
    total: int
    succeeded: int
    failed: int
    results: List[BatchGenerateResultItem]
    processing_time_seconds: float


class CloneVoiceResponse(BaseModel):
    voice_id: str
    name: str
    message: str


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: dict = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    device: str
    gpu_available: bool
    gpu_name: Optional[str] = None
    engines: List[str]
    loaded_engines: List[str]
    version: str
