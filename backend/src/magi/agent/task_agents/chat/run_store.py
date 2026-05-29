"""L0-backed session run store for chat task-agent coordination."""

from __future__ import annotations

from threading import RLock

from ....memory.l0.working_memory import L0WorkingMemoryStore
from ...run_control import RunControl
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
    """Store one active run per session_id and track revisioned results.

    In-memory companion: ``_run_controls`` holds the live ``RunControl``
    bundle for each active run keyed by ``(session_id, run_id)``. The
    bundle contains asyncio Events and inboxes that cannot be persisted;
    it is the runtime-only counterpart to the persisted ``ActiveRun``
    record. Background-restored runs do NOT have a registered control —
    callers must tolerate ``get_active_run_control`` returning ``None``.
    """

    def __init__(self, *, l0_store: L0WorkingMemoryStore | None = None) -> None:
        self._l0_store = l0_store or L0WorkingMemoryStore(restore_on_restart=False)
        self._lock = RLock()
        self._run_controls: dict[tuple[str, str], RunControl] = {}


__all__ = ["SessionRunStore"]
