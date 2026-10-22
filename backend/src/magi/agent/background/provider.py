"""Container-backed providers for background-task runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ...core.container import require_binding, optional_binding

if TYPE_CHECKING:
    from .manager import BackgroundTaskManager


def resolve_background_task_manager() -> "BackgroundTaskManager":
    """Return the active background-task manager binding."""
    return cast("BackgroundTaskManager", require_binding("background_task_manager"))


def get_optional_background_task_manager() -> "BackgroundTaskManager | None":
    return cast("BackgroundTaskManager | None", optional_binding("background_task_manager"))
