"""
Text processing utilities.

Handles:
  * Cleaning/normalizing raw input text
  * Splitting text into sentences so XTTS can be conditioned per-sentence
    (this is what gives natural pauses at punctuation and prevents the
    model from rushing/clipping long paragraphs)
  * Expanding common abbreviations so they aren't mispronounced
  * Chunking long sentences to stay under the model's safe token budget
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# XTTS-v2 degrades in quality / can clip audio past ~250 characters per
# inference call. We chunk on sentence boundaries first, then hard-wrap
# any sentence that's still too long on clause boundaries (commas, semicolons).
MAX_CHUNK_CHARS = 250

_ABBREVIATIONS = {
    r"\bMr\.": "Mister",
    r"\bMrs\.": "Missus",
    r"\bMs\.": "Miss",
    r"\bDr\.": "Doctor",
    r"\bProf\.": "Professor",
    r"\bSt\.": "Saint",
    r"\bvs\.": "versus",
    r"\be\.g\.": "for example",
    r"\bi\.e\.": "that is",
    r"\betc\.": "et cetera",
    r"\bapprox\.": "approximately",
    r"\bDept\.": "Department",
    r"\bInc\.": "Incorporated",
    r"\bJr\.": "Junior",
    r"\bSr\.": "Senior",
}

_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[,;:])\s+")
_WHITESPACE_RE = re.compile(r"\s+")
_MULTI_PUNCT_RE = re.compile(r"([.!?]){2,}")


@dataclass
class TextChunk:
    index: int
    text: str


def normalize_text(text: str) -> str:
    """Clean whitespace, expand abbreviations, normalize punctuation."""
    text = text.strip()
    text = _WHITESPACE_RE.sub(" ", text)

    for pattern, replacement in _ABBREVIATIONS.items():
        text = re.sub(pattern, replacement, text)

    # Collapse "..." / "!!" / "??" runs to a single natural punctuation mark
    text = _MULTI_PUNCT_RE.sub(r"\1", text)

    # Ensure ellipses render as a brief pause rather than being dropped
    text = text.replace("...", ", ")

    return text.strip()


def split_sentences(text: str) -> list[str]:
    """Split normalized text into sentences on terminal punctuation."""
    text = normalize_text(text)
    if not text:
        return []

    # Split on paragraph breaks first to preserve intentional long pauses
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    sentences: list[str] = []

    for para in paragraphs:
        parts = _SENTENCE_END_RE.split(para)
        for part in parts:
            part = part.strip()
            if part:
                sentences.append(part)

    return sentences


def chunk_sentence(sentence: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """If a single sentence exceeds max_chars, split it on clause boundaries."""
    if len(sentence) <= max_chars:
        return [sentence]

    clauses = _CLAUSE_SPLIT_RE.split(sentence)
    chunks: list[str] = []
    current = ""

    for clause in clauses:
        candidate = f"{current} {clause}".strip() if current else clause
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # If a single clause is still too long, hard-wrap on words
            if len(clause) > max_chars:
                words = clause.split()
                buf = ""
                for w in words:
                    cand = f"{buf} {w}".strip() if buf else w
                    if len(cand) <= max_chars:
                        buf = cand
                    else:
                        chunks.append(buf)
                        buf = w
                current = buf
            else:
                current = clause

    if current:
        chunks.append(current)

    return chunks


def prepare_chunks(text: str) -> list[TextChunk]:
    """Full pipeline: normalize -> split sentences -> sub-chunk long ones."""
    sentences = split_sentences(text)
    chunks: list[str] = []
    for sentence in sentences:
        chunks.extend(chunk_sentence(sentence))

    return [TextChunk(index=i, text=c) for i, c in enumerate(chunks)]


def estimate_duration_seconds(text: str, words_per_minute: int = 155) -> float:
    """Rough heuristic duration estimate, used only for progress UI hints."""
    word_count = max(1, len(text.split()))
    return round((word_count / words_per_minute) * 60.0, 2)
