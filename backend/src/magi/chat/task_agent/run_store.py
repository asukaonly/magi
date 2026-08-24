"""Live session run store for chat task-agent coordination."""

from __future__ import annotations

from threading import RLock
from magi.control.run_control import RunControl
from .execution_state_store import SessionExecutionStateStore
from .run_store_conversion import SessionRunConversionMixin
from .run_store_lifecycle import SessionRunLifecycleMixin
from .run_store_results import SessionRunResultMixin

class SessionRunStore(
    SessionRunLifecycleMixin,
    SessionRunResultMixin,
    SessionRunConversionMixin,
):
    """Store one live run per session and track revisioned results.

    In-memory companion: ``_run_controls`` holds the live ``RunControl``
    bundle for each active run keyed by ``(session_id, run_id)``. The
    bundle contains asyncio Events and inboxes that cannot be persisted;
    it is the runtime-only counterpart to the persisted ``ActiveRun``
    record. Process restart recovery is ledger-driven and creates a new run
    instead of restoring a control-less active record.
    """

    def __init__(
        self,
        *,
        execution_store: SessionExecutionStateStore | None = None,
        workbench_store: object | None = None,
    ) -> None:
        self._execution_store = execution_store or SessionExecutionStateStore()
        self._workbench_store = workbench_store
        self._lock = RLock()
        self._run_controls: dict[tuple[str, str], RunControl] = {}


__all__ = ["SessionRunStore"]
