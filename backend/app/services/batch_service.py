"""Batch processing service: synthesizes multiple text items sequentially,
isolating failures per-item so one bad item doesn't abort the whole batch."""

from __future__ import annotations

import time

from app.core.logging_config import get_logger
from app.models.schemas import (
    BatchGenerateItem,
    BatchGenerateRequest,
    BatchGenerateResponse,
    BatchGenerateResultItem,
    GenerateRequest,
)
from app.services.synthesis_service import generate_speech
from app.utils.file_manager import new_id

logger = get_logger(__name__)


def _item_to_request(item: BatchGenerateItem, generate_subtitles: bool) -> GenerateRequest:
    return GenerateRequest(
        text=item.text,
        voice_id=item.voice_id,
        language=item.language,
        speed=item.speed,
        pitch_semitones=item.pitch_semitones,
        output_format=item.output_format,
        generate_subtitles=generate_subtitles,
    )


def generate_batch(request: BatchGenerateRequest) -> BatchGenerateResponse:
    batch_id = new_id()
    start = time.time()
    results: list[BatchGenerateResultItem] = []
    succeeded = 0
    failed = 0

    logger.info("Starting batch job=%s items=%d", batch_id, len(request.items))

    for item in request.items:
        try:
            req = _item_to_request(item, request.generate_subtitles)
            result = generate_speech(req)
            results.append(BatchGenerateResultItem(id=item.id, success=True, result=result))
            succeeded += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Batch item '%s' failed: %s", item.id, exc)
            results.append(BatchGenerateResultItem(id=item.id, success=False, error=str(exc)))
            failed += 1

    elapsed = round(time.time() - start, 2)
    logger.info(
        "Batch job=%s complete: %d succeeded, %d failed, %.2fs",
        batch_id,
        succeeded,
        failed,
        elapsed,
    )

    return BatchGenerateResponse(
        batch_id=batch_id,
        total=len(request.items),
        succeeded=succeeded,
        failed=failed,
        results=results,
        processing_time_seconds=elapsed,
    )
