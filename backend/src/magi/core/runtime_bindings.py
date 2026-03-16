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


def require_message_bus():
    """Return the active message bus binding."""
    return _require_binding("message_bus")


def require_other_memory():
    """Return the runtime-owned other-memory binding."""
    return _require_binding("other_memory")


def require_skill_indexer():
    """Return the shared skill indexer binding."""
    return _require_binding("skill_indexer")


def require_skill_loader():
    """Return the shared skill loader binding."""
    return _require_binding("skill_loader")


def require_skill_executor():
    """Return the shared skill executor binding."""
    return _require_binding("skill_executor")
