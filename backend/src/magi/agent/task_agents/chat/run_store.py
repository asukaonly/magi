"""In-memory session run store for chat task-agent coordination."""
from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any
from uuid import uuid4

from ....memory.l0.working_memory import L0WorkingMemoryStore
from .run_contracts import ActiveRun, PendingTurn, RunResult, RunResultDisposition


class SessionRunStore:
    """Store one active run per session_id and track revisioned results."""

    def __init__(self, *, l0_store: L0WorkingMemoryStore | None = None) -> None:
        self._l0_store = l0_store or L0WorkingMemoryStore(restore_on_restart=False)
        self._lock = RLock()

    def create_active_run(
        self,
        session_id: str,
        *,
        root_turn_id: str | None = None,
        root_user_message: str = "",
        run_id: str | None = None,
    ) -> ActiveRun:
        """Create or replace the active run for a session."""
        with self._lock:
            self._l0_store.clear_execution_state_sync(session_id)
            run_identifier = run_id or uuid4().hex
            self._l0_store.upsert_execution_run_sync(
                session_id=session_id,
                run_id=run_identifier,
                status="running",
                revision=0,
                root_turn_id=root_turn_id,
                root_user_message=root_user_message,
                response_anchor_turn_id=root_turn_id,
            )
            active_run = self._require_run(session_id)
            return deepcopy(active_run)

    def get_active_run(self, session_id: str) -> ActiveRun | None:
        """Return the current active run for a session."""
        with self._lock:
            active_run = self._get_run(session_id)
            return deepcopy(active_run) if active_run is not None else None

    def append_pending_turn(self, session_id: str, turn_id: str, content: str) -> PendingTurn:
        """Attach a pending turn to the active run for the session."""
        with self._lock:
            active_run = self._require_run(session_id)
            pending_payload = self._l0_store.append_execution_pending_turn_sync(
                session_id=session_id,
                run_id=active_run.run_id,
                turn_id=turn_id,
                content=content,
                revision=active_run.revision,
            )
            pending_turn = self._to_pending_turn(pending_payload)
            return deepcopy(pending_turn)

    def set_root_turn(
        self,
        session_id: str,
        *,
        turn_id: str | None,
        content: str,
    ) -> ActiveRun:
        """Set or replace the root user turn for the active run."""
        with self._lock:
            active_run = self._require_run(session_id)
            self._l0_store.upsert_execution_run_sync(
                session_id=session_id,
                run_id=active_run.run_id,
                status="running",
                revision=active_run.revision,
                root_turn_id=turn_id,
                root_user_message=content,
                response_anchor_turn_id=turn_id,
            )
            active_run = self._require_run(session_id)
            return deepcopy(active_run)

    def consume_pending_turns(self, session_id: str) -> list[PendingTurn]:
        """Return and clear pending turns for the active run."""
        with self._lock:
            self._require_run(session_id)
            pending_turns = [
                self._to_pending_turn(item)
                for item in self._l0_store.consume_execution_pending_turns_sync(session_id)
            ]
            return pending_turns

    def bump_revision(
        self,
        session_id: str,
        *,
        root_user_message: str | None = None,
        clear_pending_turns: bool = False,
    ) -> ActiveRun:
        """Advance the active revision for a session run."""
        with self._lock:
            active_run = self._require_run(session_id)
            if clear_pending_turns:
                self._l0_store.consume_execution_pending_turns_sync(session_id)
            self._l0_store.upsert_execution_run_sync(
                session_id=session_id,
                run_id=active_run.run_id,
                status="running",
                revision=active_run.revision + 1,
                root_turn_id=active_run.root_turn_id,
                root_user_message=(
                    root_user_message if root_user_message is not None else active_run.root_user_message
                ),
                response_anchor_turn_id=active_run.root_turn_id,
            )
            active_run = self._require_run(session_id)
            return deepcopy(active_run)

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
            stale_payload = self._l0_store.record_execution_result_sync(
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
            accepted_payload = self._l0_store.record_execution_result_sync(
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
            if run_id != active_run.run_id or revision != active_run.revision:
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

    def _get_run(self, session_id: str) -> ActiveRun | None:
        state = self._l0_store.get_execution_state_sync(session_id)
        run = state.get("run")
        if not isinstance(run, dict):
            return None
        return ActiveRun(
            session_id=str(run["session_id"]),
            run_id=str(run["run_id"]),
            root_turn_id=str(run["root_turn_id"]) if run.get("root_turn_id") is not None else None,
            root_user_message=str(run.get("root_user_message") or ""),
            revision=int(run.get("revision") or 0),
            pending_turns=[self._to_pending_turn(item) for item in state.get("pending_turns", [])],
            accepted_results=[self._to_run_result(item) for item in state.get("accepted_results", [])],
            stale_results=[self._to_run_result(item) for item in state.get("stale_results", [])],
            created_at=float(run.get("created_at") or 0.0),
            updated_at=float(run.get("updated_at") or 0.0),
        )

    def _require_run(self, session_id: str) -> ActiveRun:
        active_run = self._get_run(session_id)
        if active_run is None:
            raise ValueError(f"No active run for session_id={session_id!r}")
        return active_run

    @staticmethod
    def _to_pending_turn(payload: dict[str, Any]) -> PendingTurn:
        return PendingTurn(
            turn_id=str(payload["turn_id"]),
            content=str(payload["content"]),
            revision=int(payload["revision"]),
            created_at=float(payload.get("created_at") or 0.0),
        )

    @staticmethod
    def _to_run_result(payload: dict[str, Any]) -> RunResult:
        return RunResult(
            result_id=str(payload["result_id"]),
            run_id=str(payload["run_id"]),
            revision=int(payload["revision"]),
            payload=deepcopy(payload.get("payload") or {}),
            disposition=RunResultDisposition(str(payload["disposition"])),
            created_at=float(payload.get("created_at") or 0.0),
        )
