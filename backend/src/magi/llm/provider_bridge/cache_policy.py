"""Unified prompt-cache layer: provider-capability-gated cache_control markers.

Caching is a prefix match. The renderer marks the byte-stable head of the
system prompt with ``SYSTEM_PROMPT_CACHE_BOUNDARY`` (identity and persona
definition before it are stable across turns; selected tools, persona steer,
memory, and runtime context after it vary per turn). Here we:

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


def _ephemeral(ttl: str | None = None) -> dict[str, Any]:
    """An ``ephemeral`` cache_control marker, optionally with a longer TTL.

    No ``ttl`` field means Anthropic's 5-minute default (1.25x write); ``"1h"``
    extends it to one hour (2x write) — worth it only for entries reused widely
    enough to amortize the premium. Anthropic requires any 1h breakpoint to
    appear before all 5m ones; render order (tools → system → messages) keeps a
    1h system head ahead of 5m message markers automatically.
    """
    marker: dict[str, Any] = {"type": "ephemeral"}
    if ttl:
        marker["ttl"] = ttl
    return marker


def _mark_last_block(message: dict[str, Any], ttl: str | None) -> dict[str, Any] | None:
    """Copy ``message`` with a cache_control on its last content block.

    String content is promoted to a one-element text block so the marker has
    somewhere to live. Returns None when there is nothing to mark (empty/None
    content). The input is never mutated.
    """
    content = message.get("content")
    if isinstance(content, str):
        new_content: Any = [{"type": "text", "text": content, "cache_control": _ephemeral(ttl)}]
    elif isinstance(content, list) and content:
        new_content = [dict(block) for block in content]
        new_content[-1] = {**new_content[-1], "cache_control": _ephemeral(ttl)}
    else:
        return None
    return {**message, "content": new_content}


def cache_marked_system_content(
    system: str, *, supports_marker: bool, ttl: str | None = None, cache_whole: bool = False
) -> str | list[dict[str, Any]]:
    """Return the SYSTEM field content, with a cache_control marker when applicable.

    The per-turn tail (after the boundary) is not returned here. The runtime
    materializes it as a durable turn-context message before calling the bridge,
    so the system head plus older context form one stable prefix.

    - marker vendor + boundary: a content-block list with an ``ephemeral``
      cache_control on the head (with optional ``ttl`` for marker vendors that
      support it, e.g. Anthropic's ``"1h"``). Boundary always wins, so a per-turn
      tail is never marked even when ``cache_whole`` is set.
    - marker vendor + no boundary + ``cache_whole``: mark the WHOLE system as one
      cacheable block — for auxiliary calls (routing, memory extraction) whose
      system prompt the caller knows is byte-stable but which don't go through the
      renderer's boundary machinery (#100).
    - non-marker vendor: the head/system as a plain ``str`` (auto-caching only).
    - no boundary, no ``cache_whole``: the system unchanged.
    """
    parts = split_on_boundary(system)
    if parts is None:
        if cache_whole and supports_marker and system.strip():
            return [{"type": "text", "text": system, "cache_control": _ephemeral(ttl)}]
        return system

    head, _tail = parts
    if supports_marker:
        return [{"type": "text", "text": head, "cache_control": _ephemeral(ttl)}]
    return head


def last_user_message_index(messages: list[dict[str, Any]]) -> int:
    """Index of the last ``user`` message, or -1 if there is none.

    Tool results carry role ``tool`` (not ``user``), so during a tool loop this
    still resolves to the most recent user or runtime-control message.
    """
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            return i
    return -1


def turn_context_message_index(messages: list[dict[str, Any]]) -> int:
    """Return the latest explicit turn-context snapshot index, or ``-1``."""

    from ...chat.model_context import is_turn_context_message

    for index in range(len(messages) - 1, -1, -1):
        if is_turn_context_message(messages[index]):
            return index
    return -1


def _mark_at(
    api_messages: list[dict[str, Any]], index: int, ttl: str | None
) -> list[dict[str, Any]]:
    """Return a copy of ``api_messages`` with a breakpoint on message ``index``'s
    last block; a no-op (same list, unmutated) for out-of-range or unmarkable."""
    if index < 0 or index >= len(api_messages):
        return api_messages
    marked = _mark_last_block(api_messages[index], ttl)
    if marked is None:
        return api_messages
    out = list(api_messages)
    out[index] = marked
    return out


def mark_history_breakpoint(
    api_messages: list[dict[str, Any]], boundary_index: int, *, ttl: str | None = None
) -> list[dict[str, Any]]:
    """Place an ``ephemeral`` cache_control on the last content block of the
    message at ``boundary_index`` — the stable history boundary.

    Anthropic caches by prefix and needs an explicit breakpoint; placing it on
    the message *before* the volatile per-turn context lets the older history be
    reused across turns while the current turn stays uncached (a rolling
    breakpoint). Returns a new list; the input is not mutated. Out-of-range
    indices are a no-op.
    """
    return _mark_at(api_messages, boundary_index, ttl)


def mark_tool_loop_tail_breakpoint(
    api_messages: list[dict[str, Any]], *, active: bool, ttl: str | None = None
) -> list[dict[str, Any]]:
    """Place a breakpoint on the LAST message (the growing tool-result tail).

    Within a single agentic turn the tool loop re-calls the model with an
    ever-growing message list; marking the tail lets each iteration hit the
    previous one's cache. Only when ``active`` — i.e. the raw turn ends in a
    tool result — because otherwise the last message holds the volatile per-turn
    context and marking it would just waste a (never-reused) cache write.
    Returns a new list; the input is not mutated.
    """
    if not active:
        return api_messages
    return _mark_at(api_messages, len(api_messages) - 1, ttl)
