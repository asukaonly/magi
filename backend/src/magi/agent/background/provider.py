"""Container-backed providers for background-task runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ...core.container import get_container

if TYPE_CHECKING:
    from .manager import BackgroundTaskManager


def _require_background_binding(provider_name: str) -> Any:
    provider = getattr(get_container(), provider_name)
    instance = provider()
    if instance is None:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    return instance


def resolve_background_task_manager() -> "BackgroundTaskManager":
    """Return the active background-task manager binding."""
    return cast("BackgroundTaskManager", _require_background_binding("background_task_manager"))
