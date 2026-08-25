"""Provider-neutral message markers used by model-context assembly."""

from __future__ import annotations

from typing import Any, Mapping


def build_turn_context_message(content: str) -> dict[str, str] | None:
    """Build the explicit message that freezes one turn's dynamic context."""

    normalized = str(content or "").strip()
    if not normalized:
        return None
    return {
        "role": "user",
        "content": f"<turn_context>\n{normalized}\n</turn_context>",
    }


def is_turn_context_message(message: Mapping[str, Any]) -> bool:
    """Return whether a provider-facing message is a turn-context snapshot."""

    if str(message.get("role") or "").strip() != "user":
        return False
    content = message.get("content")
    if isinstance(content, str):
        return content.lstrip().startswith("<turn_context>")
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "text":
            continue
        return str(block.get("text") or "").lstrip().startswith("<turn_context>")
    return False


__all__ = ["build_turn_context_message", "is_turn_context_message"]
