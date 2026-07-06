"""Priority routing helpers for L2 LLM calls."""

from __future__ import annotations

from typing import Any

from ...llm import LLMRequestPriority

_CHAT_SOURCE = "chat"


def l2_llm_priority_for_source(source: str | None) -> LLMRequestPriority:
    """Return the L2 LLM priority for one source."""
    normalized = str(source or "").strip().lower()
    if normalized == _CHAT_SOURCE:
        return LLMRequestPriority.MEDIUM
    return LLMRequestPriority.LOW


def l2_llm_priority_for_event_window(event_window: Any) -> LLMRequestPriority:
    """Use the window's primary event source to route L2 LLM priority."""
    return l2_llm_priority_for_source(_primary_source_for_event_window(event_window))


def _primary_source_for_event_window(event_window: Any) -> str | None:
    events = list(getattr(event_window, "events", []) or [])
    for event in reversed(events):
        source = _source_from_event(event)
        if source:
            return source
    return None


def _source_from_event(event: Any) -> str | None:
    if isinstance(event, dict):
        value = event.get("source")
    else:
        value = getattr(event, "source", None)
    text = str(value or "").strip()
    return text or None


__all__ = ["l2_llm_priority_for_event_window", "l2_llm_priority_for_source"]
