"""Word and character error rate for ASR round-trip checks.

Both sides go through the same light normalisation (case, punctuation,
whitespace, a few spelling variants) so the score reflects what was *said*,
not formatting differences between the script and the transcript.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_PUNCT = re.compile(r"[^\w\s']")
_SPACE = re.compile(r"\s+")
# Whisper's spelling vs common script spelling; keep tiny and explicit.
_VARIANTS = {"okay": "ok", "mr": "mister", "mrs": "missus", "dr": "doctor", "st": "saint"}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("’", "'").replace("-", " ")
    text = _PUNCT.sub(" ", text)
    words = [_VARIANTS.get(w.strip("'"), w.strip("'")) for w in _SPACE.split(text)]
    return " ".join(w for w in words if w)


def edit_distance(ref: list[str] | str, hyp: list[str] | str) -> int:
    """Levenshtein distance (substitutions + insertions + deletions), O(len(hyp)) memory."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, start=1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


@dataclass(frozen=True)
class ErrorCounts:
    word_errors: int
    words: int
    char_errors: int
    chars: int

    @property
    def wer(self) -> float:
        return self.word_errors / self.words if self.words else 0.0

    @property
    def cer(self) -> float:
        return self.char_errors / self.chars if self.chars else 0.0

    def __add__(self, other: ErrorCounts) -> ErrorCounts:
        return ErrorCounts(
            self.word_errors + other.word_errors,
            self.words + other.words,
            self.char_errors + other.char_errors,
            self.chars + other.chars,
        )


def score(reference: str, hypothesis: str) -> ErrorCounts:
    ref, hyp = normalize(reference), normalize(hypothesis)
    return ErrorCounts(
        word_errors=edit_distance(ref.split(), hyp.split()),
        words=len(ref.split()),
        char_errors=edit_distance(ref, hyp),
        chars=len(ref),
    )
