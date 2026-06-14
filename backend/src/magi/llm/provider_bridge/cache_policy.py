"""Unified prompt-cache layer: provider-capability-gated cache_control markers.

Caching is a prefix match. The renderer marks the byte-stable head of the
system prompt with ``SYSTEM_PROMPT_CACHE_BOUNDARY`` (everything before it —
identity/boundary/tool-catalog — is stable across turns; everything after —
persona/memory/runtime — varies per turn). Here we:

- gate by provider capability: only vendors whose wire API honors inline
  ``cache_control`` markers get them (Anthropic, Qwen/DashScope; others are
  automatic-only and must NOT receive markers — they'd be ignored or 400);
- for marker vendors, place a single ``ephemeral`` breakpoint on the stable
  head only (the dynamic tail stays unmarked so a per-turn change there never
  invalidates the cached head);
- always strip the internal boundary so it never reaches the model.

Block format (``{"type":"text","text":...,"cache_control":{"type":"ephemeral"}}``)
is identical for Anthropic's top-level ``system`` and the OpenAI-compatible
system message content, so one helper serves both. See #110.
"""

from __future__ import annotations

from typing import Any

from ...config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from ...config.models import ModelVendor

# Vendors whose API honors an inline cache_control marker. Everyone else is
# automatic/implicit-only — sending a marker is useless or rejected, so gate it.
_MARKER_VENDORS: frozenset[ModelVendor] = frozenset(
    {ModelVendor.ANTHROPIC, ModelVendor.DASHSCOPE}
)


def vendor_supports_cache_marker(vendor: ModelVendor | None) -> bool:
    return vendor in _MARKER_VENDORS


def split_on_boundary(system: str) -> tuple[str, str] | None:
    """Split into (stable_head, dynamic_tail) on the boundary, or None if absent.

    Trims the newlines the renderer's line-join leaves around the marker.
    """
    if SYSTEM_PROMPT_CACHE_BOUNDARY not in system:
        return None
    head, _, tail = system.partition(SYSTEM_PROMPT_CACHE_BOUNDARY)
    return head.rstrip("\n"), tail.lstrip("\n")


def strip_boundary(system: str) -> str:
    """Remove the internal boundary marker, rejoining head and tail."""
    parts = split_on_boundary(system)
    if parts is None:
        return system
    head, tail = parts
    return f"{head}\n{tail}" if tail else head


def cache_marked_system_content(system: str, *, supports_marker: bool) -> str | list[dict[str, Any]]:
    """Return the SYSTEM field content: the byte-stable head only.

    The per-turn tail (after the boundary) is NOT returned here — it is moved
    into the message stream by :func:`inject_turn_context`, so the system head
    plus the conversation history form one stable, cacheable prefix (#100/P2).

    - marker vendor + boundary: a content-block list with an ``ephemeral``
      cache_control on the head.
    - non-marker vendor + boundary: the head as a plain ``str``.
    - no boundary: the system unchanged (nothing to split out).
    """
    parts = split_on_boundary(system)
    if parts is None:
        return system

    head, _tail = parts
    if supports_marker:
        return [{"type": "text", "text": head, "cache_control": {"type": "ephemeral"}}]
    return head


def extract_turn_context(system: str) -> str:
    """The per-turn dynamic tail (after the boundary), or '' if no boundary."""
    parts = split_on_boundary(system)
    return parts[1] if parts is not None else ""


def _wrap_turn_context(tail: str) -> str:
    return f"<turn_context>\n{tail}\n</turn_context>"


def _prepend_text(message: dict[str, Any], text: str) -> dict[str, Any]:
    content = message.get("content")
    if isinstance(content, list):
        new_content: Any = [{"type": "text", "text": text}, *content]
    elif isinstance(content, str):
        new_content = f"{text}\n\n{content}"
    else:
        new_content = text
    return {**message, "content": new_content}


def inject_turn_context(messages: list[dict[str, Any]], system: str) -> list[dict[str, Any]]:
    """Move the system's per-turn tail into the message stream as turn context.

    The tail (memory / profile / runtime-time / attachments) is prepended —
    send-time only, never persisted — to the LAST user message, so it sits as
    context right *before* the user's current input (context-then-question, not
    after it, so it doesn't pull the model off the actual question). This keeps
    the system head + conversation history a byte-stable cacheable prefix while
    the per-turn context rides in the uncached tail (#100/P2a).

    Returns a new list; inputs are not mutated. No boundary/tail -> unchanged.
    """
    tail = extract_turn_context(system)
    if not tail:
        return messages

    ctx = _wrap_turn_context(tail)
    out = list(messages)
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user":
            out[i] = _prepend_text(out[i], ctx)
            return out
    # No user message to attach to — append the context as a trailing user turn.
    out.append({"role": "user", "content": ctx})
    return out
