"""API-facing user-message sensor binding access."""

from __future__ import annotations

from ...core.container import get_container


def require_user_message_sensor():
    """Return the shared user-message sensor from the DI container."""
    instance = get_container().user_message_sensor()
    if instance is None or type(instance).__name__ == "object":
        raise RuntimeError("user_message_sensor binding is not initialized")
    return instance


__all__ = ["require_user_message_sensor"]
