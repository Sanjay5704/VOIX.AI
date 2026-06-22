"""Custom exception hierarchy for clear, mappable error handling."""

from __future__ import annotations


class TTSAppError(Exception):
    """Base class for all application-raised errors."""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(TTSAppError):
    status_code = 422
    error_code = "validation_error"


class TextTooLongError(ValidationError):
    error_code = "text_too_long"


class EmptyTextError(ValidationError):
    error_code = "empty_text"


class VoiceNotFoundError(TTSAppError):
    status_code = 404
    error_code = "voice_not_found"


class UnsupportedAudioFormatError(ValidationError):
    error_code = "unsupported_audio_format"


class FileTooLargeError(ValidationError):
    status_code = 413
    error_code = "file_too_large"


class ModelLoadError(TTSAppError):
    status_code = 503
    error_code = "model_load_error"


class GenerationError(TTSAppError):
    status_code = 500
    error_code = "generation_error"


class GenerationTimeoutError(TTSAppError):
    status_code = 504
    error_code = "generation_timeout"


class JobNotFoundError(TTSAppError):
    status_code = 404
    error_code = "job_not_found"


class AudioProcessingError(TTSAppError):
    status_code = 500
    error_code = "audio_processing_error"


class FFmpegNotFoundError(TTSAppError):
    status_code = 503
    error_code = "ffmpeg_not_found"


class ConcurrencyLimitError(TTSAppError):
    status_code = 429
    error_code = "too_many_requests"
