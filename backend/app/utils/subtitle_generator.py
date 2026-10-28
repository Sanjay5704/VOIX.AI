"""SRT subtitle file generation from sentence-level timestamps."""

from __future__ import annotations

from pathlib import Path
from typing import List

from app.models.schemas import SentenceTimestamp


def _format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis -= 1000
        secs += 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(sentences: List[SentenceTimestamp]) -> str:
    """Build SRT-formatted subtitle text from sentence timestamps."""
    lines = []
    for s in sentences:
        lines.append(str(s.index + 1))
        lines.append(f"{_format_timestamp(s.start)} --> {_format_timestamp(s.end)}")
        lines.append(s.text)
        lines.append("")
    return "\n".join(lines)


def write_srt(sentences: List[SentenceTimestamp], output_path: Path) -> Path:
    content = generate_srt(sentences)
    # newline="" stops Windows from turning line endings into CRLF (same file on every OS)
    output_path.write_text(content, encoding="utf-8", newline="")
    return output_path
