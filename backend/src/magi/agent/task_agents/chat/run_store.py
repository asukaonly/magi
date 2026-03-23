"""In-memory session run store for chat task-agent coordination."""
from __future__ import annotations

from copy import deepcopy
from threading import RLock
from time import time
from typing import Any
from uuid import uuid4

from .run_contracts import ActiveRun, PendingTurn, RunResult, RunResultDisposition


class SessionRunStore:
    """Store one active run per session_id and track revisioned results."""

    def __init__(self) -> None:
        self._runs: dict[str, ActiveRun] = {}
        self._lock = RLock()

    def create_active_run(self, session_id: str, run_id: str | None = None) -> ActiveRun:
        """Create or replace the active run for a session."""
        active_run = ActiveRun(
            session_id=session_id,
            run_id=run_id or uuid4().hex,
        )
        self._set_run(active_run)
        return deepcopy(active_run)

    def get_active_run(self, session_id: str) -> ActiveRun | None:
        """Return the current active run for a session."""
        with self._lock:
            active_run = self._runs.get(session_id)
            return deepcopy(active_run) if active_run is not None else None

    def append_pending_turn(self, session_id: str, turn_id: str, content: str) -> PendingTurn:
        """Attach a pending turn to the active run for the session."""
        with self._lock:
            active_run = self._require_run(session_id)
            pending_turn = PendingTurn(
                turn_id=turn_id,
                content=content,
                revision=active_run.revision,
            )
            active_run.pending_turns.append(pending_turn)
            active_run.updated_at = time()
            return deepcopy(pending_turn)

    def bump_revision(self, session_id: str) -> ActiveRun:
        """Advance the active revision for a session run."""
        with self._lock:
            active_run = self._require_run(session_id)
            active_run.revision += 1
            active_run.updated_at = time()
            return deepcopy(active_run)

    def mark_stale_result(
        self,
        session_id: str,
        result_id: str,
        *,
        revision: int,
        payload: dict[str, Any],
    ) -> RunResult:
        """Record a stale result separately from accepted results."""
        with self._lock:
            active_run = self._require_run(session_id)
            stale_result = RunResult(
                result_id=result_id,
                revision=revision,
                payload=deepcopy(payload),
                disposition=RunResultDisposition.STALE,
            )
            active_run.stale_results.append(stale_result)
            active_run.updated_at = time()
            return deepcopy(stale_result)

    def mark_accepted_result(
        self,
        session_id: str,
        result_id: str,
        *,
        revision: int,
        payload: dict[str, Any],
    ) -> RunResult:
        """Record an accepted result for the current run revision."""
        with self._lock:
            active_run = self._require_run(session_id)
            accepted_result = RunResult(
                result_id=result_id,
                revision=revision,
                payload=deepcopy(payload),
                disposition=RunResultDisposition.ACCEPTED,
            )
            active_run.accepted_results.append(accepted_result)
            active_run.updated_at = time()
            return deepcopy(accepted_result)

    def record_result(
        self,
        session_id: str,
        result_id: str,
        *,
        revision: int,
        payload: dict[str, Any],
    ) -> RunResult:
        """Route a result to accepted or stale storage based on revision."""
        with self._lock:
            active_run = self._require_run(session_id)
            if revision < active_run.revision:
                return self.mark_stale_result(
                    session_id,
                    result_id,
                    revision=revision,
                    payload=payload,
                )
            return self.mark_accepted_result(
                session_id,
                result_id,
                revision=revision,
                payload=payload,
            )

    def _set_run(self, active_run: ActiveRun) -> None:
        with self._lock:
            self._runs[active_run.session_id] = active_run

    def _require_run(self, session_id: str) -> ActiveRun:
        active_run = self._runs.get(session_id)
        if active_run is None:
            raise ValueError(f"No active run for session_id={session_id!r}")
        return active_run
