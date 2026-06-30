"""Utilities for chunking long memory texts before embedding."""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_CHUNK_MAX_CHARS = 600
DEFAULT_CHUNK_OVERLAP_CHARS = 120
_MIN_BREAK_RATIO = 0.6

DEFAULT_SENTENCE_MIN_CHARS = 8
DEFAULT_SENTENCE_TARGET_CHARS = 400

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


@dataclass(frozen=True, slots=True)
class _TextSegment:
    """A stripped text segment and its offsets in the normalized source."""

    char_start: int
    char_end: int
    text: str


def _single_chunk(text: str) -> list[ChunkedText]:
    return [
        ChunkedText(
            chunk_id="chunk-0",
            text=text,
            chunk_index=0,
            char_start=0,
            char_end=len(text),
            token_estimate=max(1, len(text) // 4),
        )
    ]


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

    safe_max_chars, safe_overlap = _safe_chunk_limits(max_chars, overlap_chars)

    if len(normalized) <= safe_max_chars:
        return _single_chunk(normalized)

    chunks: list[ChunkedText] = []
    start = 0
    chunk_index = 0
    min_break_position = int(safe_max_chars * _MIN_BREAK_RATIO)

    while start < len(normalized):
        end = _chunk_end(normalized, start, safe_max_chars, min_break_position)
        chunk = _chunk_from_range(normalized, start, end, chunk_index)
        if chunk is None:
            if end <= start:
                break
            start = end
            continue

        chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - safe_overlap, start + 1)
        chunk_index += 1

    return chunks


def _safe_chunk_limits(max_chars: int, overlap_chars: int) -> tuple[int, int]:
    safe_max_chars = max(1, int(max_chars))
    safe_overlap = max(0, min(int(overlap_chars), safe_max_chars - 1)) if safe_max_chars > 1 else 0
    return safe_max_chars, safe_overlap


def _chunk_end(
    normalized: str,
    start: int,
    safe_max_chars: int,
    min_break_position: int,
) -> int:
    candidate_end = min(start + safe_max_chars, len(normalized))
    if candidate_end >= len(normalized):
        return candidate_end
    best_break = _best_chunk_break(normalized, start, candidate_end)
    if best_break >= start + min_break_position:
        return best_break + 1
    return candidate_end


def _best_chunk_break(normalized: str, start: int, candidate_end: int) -> int:
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
    return max(breakpoints)


def _chunk_from_range(
    normalized: str,
    start: int,
    end: int,
    chunk_index: int,
) -> ChunkedText | None:
    raw_chunk = normalized[start:end]
    stripped = raw_chunk.strip()
    if not stripped:
        return None
    left_trim = len(raw_chunk) - len(raw_chunk.lstrip())
    right_trim = len(raw_chunk) - len(raw_chunk.rstrip())
    char_start = start + left_trim
    char_end = end - right_trim
    return ChunkedText(
        chunk_id=f"chunk-{chunk_index}",
        text=stripped,
        chunk_index=chunk_index,
        char_start=char_start,
        char_end=char_end,
        token_estimate=max(1, len(stripped) // 4),
    )


def chunk_sentences(
    text: str,
    *,
    min_chars: int = DEFAULT_SENTENCE_MIN_CHARS,
    target_chars: int = DEFAULT_SENTENCE_TARGET_CHARS,
) -> list[ChunkedText]:
    """Split *text* into sentence-group chunks for vector indexing.

    Adjacent sentences are grouped together until reaching *target_chars*
    (weighted length) so that each chunk carries enough context for a
    quality embedding.  Very short sentences (< *min_chars*) are always
    merged into the preceding group first.
    """

    normalized = str(text or "").strip()
    if not normalized:
        return []

    safe_target = max(1, int(target_chars))

    if _weighted_len(normalized) <= safe_target:
        return _single_chunk(normalized)

    raw_segments = _sentence_segments(normalized)
    if not raw_segments:
        return _single_chunk(normalized)

    merged = _merge_short_sentence_segments(
        normalized,
        raw_segments,
        min_chars=min_chars,
    )
    grouped = _group_sentence_segments(
        normalized,
        merged,
        target_chars=safe_target,
    )
    return _chunks_from_segments(grouped)


def _sentence_segments(normalized: str) -> list[_TextSegment]:
    split_ends = [m.end() for m in _SENTENCE_BOUNDARY_RE.finditer(normalized)]
    if not split_ends:
        return []

    cuts = [0, *split_ends]
    if cuts[-1] < len(normalized):
        cuts.append(len(normalized))

    segments: list[_TextSegment] = []
    for index in range(len(cuts) - 1):
        segment = _stripped_segment(normalized, cuts[index], cuts[index + 1])
        if segment is not None:
            segments.append(segment)
    return segments


def _stripped_segment(
    normalized: str,
    start: int,
    end: int,
) -> _TextSegment | None:
    raw_text = normalized[start:end]
    segment_text = raw_text.strip()
    if not segment_text:
        return None
    left_trim = len(raw_text) - len(raw_text.lstrip())
    right_trim = len(raw_text) - len(raw_text.rstrip())
    return _TextSegment(
        char_start=start + left_trim,
        char_end=end - right_trim,
        text=segment_text,
    )


def _merge_short_sentence_segments(
    normalized: str,
    segments: list[_TextSegment],
    *,
    min_chars: int,
) -> list[_TextSegment]:
    merged = [segments[0]]
    for segment in segments[1:]:
        if _weighted_len(segment.text) < min_chars and merged:
            prev_start = merged[-1].char_start
            combined = _stripped_segment(normalized, prev_start, segment.char_end)
            if combined is not None:
                merged[-1] = combined
            continue
        merged.append(segment)
    return merged


def _group_sentence_segments(
    normalized: str,
    segments: list[_TextSegment],
    *,
    target_chars: int,
) -> list[_TextSegment]:
    grouped: list[_TextSegment] = []
    group_start = segments[0].char_start
    group_end = segments[0].char_end

    for segment in segments[1:]:
        candidate = normalized[group_start : segment.char_end]
        if _weighted_len(candidate) > target_chars:
            grouped.append(
                _TextSegment(
                    char_start=group_start,
                    char_end=group_end,
                    text=normalized[group_start:group_end],
                )
            )
            group_start = segment.char_start
        group_end = segment.char_end

    grouped.append(
        _TextSegment(
            char_start=group_start,
            char_end=group_end,
            text=normalized[group_start:group_end],
        )
    )
    return grouped


def _chunks_from_segments(segments: list[_TextSegment]) -> list[ChunkedText]:
    return [
        ChunkedText(
            chunk_id=f"chunk-{index}",
            text=segment.text,
            chunk_index=index,
            char_start=segment.char_start,
            char_end=segment.char_end,
            token_estimate=max(1, len(segment.text) // 4),
        )
        for index, segment in enumerate(segments)
    ]


__all__ = ["ChunkedText", "chunk_sentences", "chunk_text"]
