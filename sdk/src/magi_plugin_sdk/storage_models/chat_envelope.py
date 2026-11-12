"""Shared chat persistence contracts and value codecs."""

from __future__ import annotations
import json
from typing import Any


def normalize_runtime_envelope(value: object) -> dict[str, Any]:
    """Copy one JSON-compatible envelope into its durable normalized shape."""

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("Runtime delivery envelope must be an object")
    normalized = deserialize_runtime_envelope(serialize_runtime_envelope(value))
    if not normalized:
        return {}
    return normalized


def serialize_runtime_envelope(value: object) -> str:
    """Serialize one envelope deterministically for request identity checks."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def deserialize_runtime_envelope(value: object) -> dict[str, Any]:
    """Decode one stored envelope, returning an empty object for corrupt JSON."""

    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def runtime_workspace_path(runtime_envelope: dict[str, Any]) -> str | None:
    """Read the accepted workspace path from a normalized delivery envelope."""

    raw_path = runtime_envelope.get("workspace_path")
    if not isinstance(raw_path, str):
        return None
    return raw_path.strip() or None
