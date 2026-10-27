"""Worker-side error types.

`retryable` tells the runner whether to report the failure as transient
(the API requeues the job) or permanent (bad input, rejected clip, ...).
"""

from __future__ import annotations

from typing import Any, Optional


class WorkerError(Exception):
    retryable: bool = False

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AudioProcessingError(WorkerError):
    pass


class FFmpegNotFoundError(WorkerError):
    pass


class InvalidJobError(WorkerError):
    """The job's params can never succeed (unknown voice, empty text, ...)."""


class EngineError(WorkerError):
    """Model failed mid-synthesis; worth another attempt (OOM, CUDA hiccup)."""

    retryable = True


class JobCanceled(WorkerError):
    """The API told us (via heartbeat) that the user canceled this job."""
