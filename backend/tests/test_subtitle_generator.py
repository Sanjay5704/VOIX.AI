"""Unit tests for app.utils.subtitle_generator."""

from app.models.schemas import SentenceTimestamp
from app.utils.subtitle_generator import _format_timestamp, generate_srt


def test_format_timestamp_basic():
    assert _format_timestamp(0.0) == "00:00:00,000"
    assert _format_timestamp(65.5) == "00:01:05,500"
    assert _format_timestamp(3661.25) == "01:01:01,250"


def test_generate_srt_structure():
    sentences = [
        SentenceTimestamp(index=0, text="Hello world.", start=0.0, end=1.2),
        SentenceTimestamp(index=1, text="Goodbye.", start=1.5, end=2.3),
    ]
    srt = generate_srt(sentences)
    assert "1\n00:00:00,000 --> 00:00:01,200\nHello world." in srt
    assert "2\n00:00:01,500 --> 00:00:02,300\nGoodbye." in srt


def test_generate_srt_empty():
    assert generate_srt([]) == ""
