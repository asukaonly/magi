"""Canonical evidence matching with offsets into the unchanged source text."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _CanonicalText:
    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]


def find_canonical_occurrence(
    content: str, evidence_text: str, *, base_offset: int = 0
) -> tuple[int, int] | None:
    """Match normalized evidence while retaining original character offsets."""
    needle = _canonical_text(evidence_text)
    if not needle:
        return None
    canonical = _canonical_text_with_offsets(content, base_offset=base_offset)
    start = canonical.text.find(needle)
    if start < 0:
        return None
    return canonical.starts[start], canonical.ends[start + len(needle) - 1]


def _canonical_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _canonical_text_with_offsets(value: str, *, base_offset: int) -> _CanonicalText:
    output: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    pending_space: tuple[int, int] | None = None
    index = 0

    while index < len(value):
        cluster_start = index
        index += 1
        while index < len(value) and unicodedata.category(value[index]).startswith("M"):
            index += 1
        cluster_end = index
        transformed = unicodedata.normalize(
            "NFKC",
            value[cluster_start:cluster_end],
        ).casefold()
        raw_start = base_offset + cluster_start
        raw_end = base_offset + cluster_end
        for character in transformed:
            if character.isspace():
                if pending_space is None:
                    pending_space = (raw_start, raw_end)
                else:
                    pending_space = (pending_space[0], raw_end)
                continue
            if pending_space is not None and output:
                output.append(" ")
                starts.append(pending_space[0])
                ends.append(pending_space[1])
            pending_space = None
            output.append(character)
            starts.append(raw_start)
            ends.append(raw_end)

    return _CanonicalText(
        text="".join(output),
        starts=tuple(starts),
        ends=tuple(ends),
    )
