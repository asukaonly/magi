"""Utilities for chunking long memory texts before embedding."""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_CHUNK_MAX_CHARS = 600
DEFAULT_CHUNK_OVERLAP_CHARS = 120
_MIN_BREAK_RATIO = 0.6


@dataclass(frozen=True, slots=True)
class ChunkedText:
    """One chunk of a larger source text."""

    chunk_id: str
    text: str
    chunk_index: int
    char_start: int
    char_end: int
    token_estimate: int


def chunk_text(
    text: str,
    *,
    max_chars: int = DEFAULT_CHUNK_MAX_CHARS,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
) -> list[ChunkedText]:
    """Split *text* into overlapping chunks using simple sentence/space breaks."""

    normalized = str(text or "")
    if not normalized:
        return []

    safe_max_chars = max(1, int(max_chars))
    safe_overlap = max(0, min(int(overlap_chars), safe_max_chars - 1)) if safe_max_chars > 1 else 0

    if len(normalized) <= safe_max_chars:
        return [
            ChunkedText(
                chunk_id="chunk-0",
                text=normalized,
                chunk_index=0,
                char_start=0,
                char_end=len(normalized),
                token_estimate=max(1, len(normalized) // 4),
            )
        ]

    chunks: list[ChunkedText] = []
    start = 0
    chunk_index = 0
    min_break_position = int(safe_max_chars * _MIN_BREAK_RATIO)

    while start < len(normalized):
        candidate_end = min(start + safe_max_chars, len(normalized))
        end = candidate_end
        if candidate_end < len(normalized):
            breakpoints = (
                normalized.rfind("\n\n", start, candidate_end),
                normalized.rfind(". ", start, candidate_end),
                normalized.rfind("。", start, candidate_end),
                normalized.rfind("! ", start, candidate_end),
                normalized.rfind("！", start, candidate_end),
                normalized.rfind("? ", start, candidate_end),
                normalized.rfind("？", start, candidate_end),
                normalized.rfind(" ", start, candidate_end),
            )
            best_break = max(breakpoints)
            if best_break >= start + min_break_position:
                end = best_break + 1

        raw_chunk = normalized[start:end]
        stripped = raw_chunk.strip()
        if not stripped:
            if end <= start:
                break
            start = end
            continue

        left_trim = len(raw_chunk) - len(raw_chunk.lstrip())
        right_trim = len(raw_chunk) - len(raw_chunk.rstrip())
        char_start = start + left_trim
        char_end = end - right_trim
        chunks.append(
            ChunkedText(
                chunk_id=f"chunk-{chunk_index}",
                text=stripped,
                chunk_index=chunk_index,
                char_start=char_start,
                char_end=char_end,
                token_estimate=max(1, len(stripped) // 4),
            )
        )
        if end >= len(normalized):
            break
        start = max(end - safe_overlap, start + 1)
        chunk_index += 1

    return chunks


__all__ = ["ChunkedText", "chunk_text"]
