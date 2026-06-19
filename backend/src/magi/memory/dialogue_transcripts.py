"""Utilities for lightweight dialogue transcript parsing."""

from __future__ import annotations

import re

_SPEAKER_SAID_RE = re.compile(
    r"(?m)^\s*(?P<speaker>[A-Z][A-Za-z0-9 .'\-]{0,80}?)\s+said,\s*[\"“]"
)


def extract_dialogue_speaker(text: str | None) -> str | None:
    """Extract the speaker name from transcript lines like ``Caroline said, "..."``."""
    match = _SPEAKER_SAID_RE.search(str(text or ""))
    if not match:
        return None
    speaker = " ".join(match.group("speaker").strip().split())
    return speaker or None


def dialogue_speaker_entity_id(speaker: str | None) -> str | None:
    text = str(speaker or "").strip()
    if not text:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    if not slug:
        return None
    return f"person:{slug}"


__all__ = ["dialogue_speaker_entity_id", "extract_dialogue_speaker"]
