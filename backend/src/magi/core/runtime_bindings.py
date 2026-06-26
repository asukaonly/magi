"""Container-backed runtime binding helpers for API and transport consumers."""

from __future__ import annotations

from .container import get_container


def _require_binding(provider_name: str):
    container = get_container()
    provider = getattr(container, provider_name)
    instance = provider()
    if instance is None:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    return instance


def require_runtime_command_queue():
    """Return the active runtime command queue binding."""
    return _require_binding("runtime_command_queue")


def require_agent_runtime():
    """Return the active agent runtime binding."""
    return _require_binding("agent_runtime")


def require_scheduler_service():
    """Return the active scheduler service binding."""
    return _require_binding("scheduler_service")


def require_chat_portrait_service():
    """Return the active chat portrait service binding."""
    return _require_binding("chat_portrait_service")
