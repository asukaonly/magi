"""L0-backed session run store for chat task-agent coordination."""

from __future__ import annotations

from threading import RLock

from ....memory.l0.working_memory import L0WorkingMemoryStore
from .run_store_conversion import SessionRunConversionMixin
from .run_store_goals import SessionRunGoalMixin
from .run_store_lifecycle import SessionRunLifecycleMixin
from .run_store_results import SessionRunResultMixin


class SessionRunStore(
    SessionRunLifecycleMixin,
    SessionRunResultMixin,
    SessionRunConversionMixin,
    SessionRunGoalMixin,
):
    """Store one active run per session_id and track revisioned results."""

    def __init__(self, *, l0_store: L0WorkingMemoryStore | None = None) -> None:
        self._l0_store = l0_store or L0WorkingMemoryStore(restore_on_restart=False)
        self._lock = RLock()


__all__ = ["SessionRunStore"]
