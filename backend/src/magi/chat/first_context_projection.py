"""Durable confirmation for first-context chat memory projection."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ..core.logger import get_logger
from ..events.events import EventTypes
from ..events.first_context import FIRST_CONTEXT_METADATA_KEY

logger = get_logger(__name__)

_FIRST_CONTEXT_PROJECTION_CONFIRM_TIMEOUT_SECONDS = 1.0
_FIRST_CONTEXT_PROJECTION_CONFIRM_INTERVAL_SECONDS = 0.02
CHAT_PROJECTION_METADATA_KEYS = frozenset(
    {
        FIRST_CONTEXT_METADATA_KEY,
        "l2_batch_owner",
        "l2_batch_catch_up_owner",
        "l2_batch_max_events",
        "l2_batch_max_estimated_tokens",
        "l2_batch_min_ready_events",
        "l2_batch_max_wait_seconds",
    }
)


def extract_chat_projection_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Keep only metadata consumed by the durable chat projection path."""

    return {
        key: value
        for key, value in metadata.items()
        if key in CHAT_PROJECTION_METADATA_KEYS and value is not None
    }


async def wait_for_first_context_memory_projection(*, message_id: str) -> bool:
    """Confirm the memory subscriber reached every required durable stage."""

    try:
        unified_memory = _resolve_projection_memory()
    except RuntimeError as exc:
        if _memory_layer_enabled("l1") is False:
            return True
        logger.warning("First-context memory confirmation is unavailable: %s", exc)
        return False

    l1_store = getattr(unified_memory, "l1", None)
    if l1_store is None:
        return _memory_layer_enabled("l1") is False
    finder = getattr(l1_store, "find_event_id_by_idempotency", None)
    event_reader = getattr(l1_store, "get_memory_event", None)
    if not callable(finder) or not callable(event_reader):
        return False

    l2_store = getattr(unified_memory, "l2", None)
    has_projection_job = getattr(l2_store, "has_projection_job", None)
    deadline = time.monotonic() + _FIRST_CONTEXT_PROJECTION_CONFIRM_TIMEOUT_SECONDS
    while True:
        event_id = await finder(
            source="chat",
            event_type=EventTypes.USER_MESSAGE,
            idempotency_key=message_id,
        )
        if event_id is not None:
            memory_event = await event_reader(event_id)
            if memory_event is not None:
                if not _event_requires_l2_projection(memory_event):
                    return True
                if _memory_layer_enabled("l2") is False:
                    return True
                if l2_store is None or not callable(has_projection_job):
                    return False
                if await has_projection_job(event_id=event_id):
                    return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(_FIRST_CONTEXT_PROJECTION_CONFIRM_INTERVAL_SECONDS)


def _event_requires_l2_projection(memory_event: object) -> bool:
    from ..memory.evidence import event_allows_l2_projection

    return event_allows_l2_projection(memory_event)


def _resolve_projection_memory():
    from ..memory.provider import get_unified_memory

    return get_unified_memory()


def _memory_layer_enabled(layer_name: str) -> bool | None:
    try:
        from ..config.loader import get_config

        layer = getattr(get_config().agent.memory, layer_name)
        return bool(layer.enabled)
    except Exception:
        return None
