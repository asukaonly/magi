"""Utilities for chunking long memory texts before embedding."""

from __future__ import annotations

import re
from dataclasses import dataclass


DEFAULT_CHUNK_MAX_CHARS = 600
DEFAULT_CHUNK_OVERLAP_CHARS = 120
_MIN_BREAK_RATIO = 0.6

DEFAULT_SENTENCE_MIN_CHARS = 8

# CJK Unified Ideographs range for weighted length calculation.
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def _weighted_len(text: str) -> float:
    """Character length with CJK chars counted as 2.5 (higher semantic density)."""
    cjk_count = len(_CJK_RE.findall(text))
    return len(text) + cjk_count * 1.5

# Matches boundaries between sentences (the separator consumed by split).
_SENTENCE_BOUNDARY_RE = re.compile(
    r"(?<=[.!?])\s+"  # English EOS punctuation + whitespace
    r"|(?<=[。！？])\s*"  # CJK EOS punctuation + optional whitespace
    r"|\n{2,}\s*"  # Paragraph break (double newline)
)


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


def chunk_sentences(
    text: str,
    *,
    min_chars: int = DEFAULT_SENTENCE_MIN_CHARS,
) -> list[ChunkedText]:
    """Split *text* into sentence-level chunks for fine-grained vector indexing.

    Each sentence becomes its own chunk so that secondary facts buried
    in a multi-topic message get their own embedding vector.

    Sentences shorter than *min_chars* are merged into the preceding
    chunk to avoid noisy low-context vectors.
    """

    normalized = str(text or "").strip()
    if not normalized:
        return []

    # Find sentence boundary positions.
    split_ends: list[int] = [m.end() for m in _SENTENCE_BOUNDARY_RE.finditer(normalized)]

    if not split_ends:
        # No sentence boundary found → single chunk (same as whole text).
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

    # Cut text at boundary positions.
    cuts = [0, *split_ends]
    if cuts[-1] < len(normalized):
        cuts.append(len(normalized))

    raw_segments: list[tuple[int, int, str]] = []
    for i in range(len(cuts) - 1):
        seg_start = cuts[i]
        seg_end = cuts[i + 1]
        seg_text = normalized[seg_start:seg_end].strip()
        if not seg_text:
            continue
        # Compute char offsets in the stripped source.
        actual_start = seg_start + (len(normalized[seg_start:seg_end]) - len(normalized[seg_start:seg_end].lstrip()))
        actual_end = seg_end - (len(normalized[seg_start:seg_end]) - len(normalized[seg_start:seg_end].rstrip()))
        raw_segments.append((actual_start, actual_end, seg_text))

    if not raw_segments:
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

    # Merge short segments into the preceding one.
    merged: list[tuple[int, int, str]] = [raw_segments[0]]
    for seg_start, seg_end, seg_text in raw_segments[1:]:
        if _weighted_len(seg_text) < min_chars and merged:
            prev_start, _, _ = merged[-1]
            combined_text = normalized[prev_start:seg_end].strip()
            combined_actual_start = prev_start + (
                len(normalized[prev_start:seg_end]) - len(normalized[prev_start:seg_end].lstrip())
            )
            combined_actual_end = seg_end - (
                len(normalized[prev_start:seg_end]) - len(normalized[prev_start:seg_end].rstrip())
            )
            merged[-1] = (combined_actual_start, combined_actual_end, combined_text)
        else:
            merged.append((seg_start, seg_end, seg_text))

    chunks: list[ChunkedText] = []
    for idx, (c_start, c_end, c_text) in enumerate(merged):
        chunks.append(
            ChunkedText(
                chunk_id=f"chunk-{idx}",
                text=c_text,
                chunk_index=idx,
                char_start=c_start,
                char_end=c_end,
                token_estimate=max(1, len(c_text) // 4),
            )
        )
    return chunks


__all__ = ["ChunkedText", "chunk_sentences", "chunk_text"]
