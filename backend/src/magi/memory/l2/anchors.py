"""Shared low-value anchor helpers for L2 episodic grouping."""

from __future__ import annotations

import re
from typing import Any

GENERIC_EXPERIENCE_ANCHORS = {
    "browser",
    "chrome",
    "gmail",
    "google",
    "google search",
    "github",
    "local user",
    "local_user",
    "self",
    "software:chrome",
    "software:gmail",
    "software:google",
    "software:github",
    "twitter",
    "user",
    "user local user",
    "user self",
    "user:local_user",
    "x",
    "x formerly twitter",
}
MACHINE_ID_PATTERN = re.compile(r"^(?:[0-9a-f]{10,}|[0-9A-HJKMNP-TV-Z]{12,})$", re.IGNORECASE)


def canonical_anchor(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(text.split())


def anchor_leaf(value: Any) -> str:
    text = str(value or "").strip()
    if ":" in text:
        _, _, text = text.partition(":")
    return text.strip()


def is_generic_experience_anchor(value: Any) -> bool:
    """Return True when an anchor is too generic to justify grouping."""
    raw = str(value or "").strip()
    leaf = anchor_leaf(raw)
    canonical_values = {canonical_anchor(raw), canonical_anchor(leaf)}
    if not raw or not leaf:
        return True
    if canonical_anchor(raw).startswith("hardware:"):
        return True
    if MACHINE_ID_PATTERN.fullmatch(raw) or MACHINE_ID_PATTERN.fullmatch(leaf):
        return True
    return any(item in GENERIC_EXPERIENCE_ANCHORS for item in canonical_values)


__all__ = [
    "GENERIC_EXPERIENCE_ANCHORS",
    "MACHINE_ID_PATTERN",
    "anchor_leaf",
    "canonical_anchor",
    "is_generic_experience_anchor",
]
