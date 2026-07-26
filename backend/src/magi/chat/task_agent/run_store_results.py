"""Result routing for chat session runs."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any

from magi.agent.task_agents.handlers.run_contracts import RunResult, RunResultDisposition


class SessionRunResultMixin:
    """Record accepted and stale run results based on active revision state."""

    _lock: RLock
    _execution_store: Any

    def mark_stale_result(
        self,
        session_id: str,
        run_id: str,
        result_id: str,
        *,
        revision: int,
        payload: dict[str, Any],
    ) -> RunResult:
        """Record a stale result separately from accepted results."""
        with self._lock:
            self._require_run(session_id)
            stale_payload = self._execution_store.record_execution_result_sync(
                session_id=session_id,
                run_id=run_id,
                result_id=result_id,
                revision=revision,
                disposition=RunResultDisposition.STALE.value,
                payload=payload,
            )
            stale_result = self._to_run_result(stale_payload)
            return deepcopy(stale_result)

    def mark_accepted_result(
        self,
        session_id: str,
        run_id: str,
        result_id: str,
        *,
        revision: int,
        payload: dict[str, Any],
    ) -> RunResult:
        """Record an accepted result for the current run revision."""
        with self._lock:
            self._require_run(session_id)
            accepted_payload = self._execution_store.record_execution_result_sync(
                session_id=session_id,
                run_id=run_id,
                result_id=result_id,
                revision=revision,
                disposition=RunResultDisposition.ACCEPTED.value,
                payload=payload,
            )
            accepted_result = self._to_run_result(accepted_payload)
            return deepcopy(accepted_result)

    def record_result(
        self,
        session_id: str,
        run_id: str,
        result_id: str,
        *,
        revision: int,
        payload: dict[str, Any],
    ) -> RunResult:
        """Route a result to accepted or stale storage based on revision."""
        with self._lock:
            active_run = self._require_run(session_id)
            if (
                run_id != active_run.run_id
                or revision != active_run.revision
                or active_run.status in {"cancelling", "cancelled"}
            ):
                return self.mark_stale_result(
                    session_id,
                    run_id,
                    result_id,
                    revision=revision,
                    payload=payload,
                )
            return self.mark_accepted_result(
                session_id,
                run_id,
                result_id,
                revision=revision,
                payload=payload,
            )


__all__ = ["SessionRunResultMixin"]
