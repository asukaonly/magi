"""Privacy-minimized fingerprints for durable agent context records."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


_SOURCE_REFERENCE_KEYS = (
    "source",
    "source_type",
    "kind",
    "id",
    "source_id",
    "message_id",
    "turn_id",
    "memory_id",
    "skill_id",
    "attachment_id",
)


def stable_hash(value: Any) -> str:
    """Return a deterministic digest without retaining the input value."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def serialized_size(value: Any) -> int:
    """Return the encoded JSON size used for operational diagnostics."""

    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def message_fingerprints(messages: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Describe model messages without copying user or attachment content."""

    return tuple(
        {
            "index": index,
            "role": str(message.get("role") or "unknown"),
            "digest": stable_hash(message),
            "size_bytes": serialized_size(message),
            "has_images": _contains_image(message.get("content")),
        }
        for index, message in enumerate(messages)
    )


def context_source_refs(
    sources: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Keep source provenance and a digest while dropping rendered source content."""

    refs: list[dict[str, Any]] = []
    for source in sources:
        ref = {
            key: source[key]
            for key in _SOURCE_REFERENCE_KEYS
            if source.get(key) is not None and isinstance(source.get(key), (str, int, float, bool))
        }
        ref["digest"] = stable_hash(source)
        ref["size_bytes"] = serialized_size(source)
        refs.append(ref)
    return tuple(refs)


def effective_context_fingerprint(
    *,
    mode: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    reasoning_state: dict[str, Any],
) -> dict[str, Any]:
    """Build a bounded journal event for one effective model context."""

    return {
        "mode": mode,
        "system_prompt_hash": stable_hash(system_prompt),
        "system_prompt_size_bytes": len(system_prompt.encode("utf-8")),
        "message_count": len(messages),
        "message_hash": stable_hash(messages),
        "message_size_bytes": serialized_size(messages),
        "tool_count": len(tools),
        "tool_schema_hash": stable_hash(tools),
        "tool_schema_size_bytes": serialized_size(tools),
        "reasoning_state": dict(reasoning_state),
    }


def _contains_image(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, dict)
        and str(block.get("type") or "") in {"image", "image_url", "input_image"}
        for block in content
    )


__all__ = [
    "context_source_refs",
    "effective_context_fingerprint",
    "message_fingerprints",
    "serialized_size",
    "stable_hash",
]
