"""Shared message-bus service for API/runtime bridges."""

from __future__ import annotations

from typing import Any

_message_bus: Any = None


def set_message_bus(message_bus: Any) -> None:
    """Set message bus instance for API-layer access."""
    global _message_bus
    _message_bus = message_bus


def get_message_bus():
    """Get message bus instance from DI container, with global fallback."""
    try:
        from ...core.container import get_container

        container = get_container()
        instance = container.message_bus()
        if instance is not None and type(instance).__name__ != "object":
            return instance
    except Exception:
        pass
    return _message_bus
