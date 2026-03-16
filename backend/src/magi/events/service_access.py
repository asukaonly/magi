"""Shared message-bus access helpers for bridge and API integrations."""

from __future__ import annotations

from ..core.runtime_bindings import require_message_bus


def get_message_bus():
    """Return the active message bus binding."""
    return require_message_bus()

__all__ = ["get_message_bus"]
