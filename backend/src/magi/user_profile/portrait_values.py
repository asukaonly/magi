"""Shared value rendering for portrait projections.

Both the materialized portrait projection and the API fallback path render L2
values and ToM snapshot ``core_traits`` through these helpers so the resulting
text is identical regardless of which path serves the page.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def display_value(value: Any) -> str:
    """Render a stored L2/snapshot value as user-facing display text.

    Unwraps JSON-encoded ``{"value": ...}`` envelopes and joins list values
    with a Chinese enumeration comma, mirroring how preference/state values are
    persisted.
    """
    parsed = _parse_value(value)
    if isinstance(parsed, dict):
        if "value" in parsed:
            return display_value(parsed.get("value"))
        return ""
    if isinstance(parsed, list):
        return "、".join(text for text in (display_value(item) for item in parsed) if text)
    return _text(parsed)


def correction_value(value: Any) -> str:
    """Return the stored assertion value used for a lossless correction round trip."""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return _text(value)


def snapshot_recent_values(snapshot: Mapping[str, Any] | None) -> list[str]:
    """Return per-trait display values from a ToM snapshot's ``core_traits``.

    A dict of traits yields one value per entry; a scalar yields a single value.
    Empty values are dropped. This is the single rendering used by both portrait
    paths so a multi-trait snapshot is never collapsed into one concatenated
    blob on one path and split into separate items on the other.
    """
    if not snapshot:
        return []
    core_traits = snapshot.get("core_traits")
    values: list[str] = []
    if isinstance(core_traits, dict):
        for value in core_traits.values():
            text = display_value(value)
            if text:
                values.append(text)
    else:
        text = display_value(core_traits)
        if text:
            values.append(text)
    return values


def _parse_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{\"":
        return value
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _text(value: Any) -> str:
    return str(value or "").strip()


__all__ = ["correction_value", "display_value", "snapshot_recent_values"]
