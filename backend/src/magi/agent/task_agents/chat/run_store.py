"""L0-backed session run store for chat task-agent coordination."""
from __future__ import annotations

from copy import deepcopy
from threading import RLock
from time import time
from typing import Any
from uuid import uuid4

from ....core.logger import get_logger
from ....memory.l0.working_memory import L0WorkingMemoryStore
from .run_contracts import ActiveRun, PendingTurn, RunResult, RunResultDisposition

logger = get_logger(__name__)


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
            self._push_root_goal(
                session_id=session_id,
                run_id=run_identifier,
                revision=0,
                root_user_message=root_user_message,
            )
            active_run = self._require_run(session_id)
            logger.info(
                "Chat session run created",
                session_id=session_id,
                run_id=active_run.run_id,
                revision=active_run.revision,
                root_turn_id=active_run.root_turn_id,
            )
            return deepcopy(active_run)

    def get_active_run(self, session_id: str) -> ActiveRun | None:
        """Return the current active run for a session."""
        with self._lock:
            active_run = self._get_run(session_id)
            return deepcopy(active_run) if active_run is not None else None

    def append_pending_turn(
        self,
        session_id: str,
        turn_id: str,
        content: str,
        *,
        disposition: str = "augment",
    ) -> PendingTurn:
        """Attach a pending turn to the active run for the session."""
        with self._lock:
            active_run = self._require_run(session_id)
            pending_payload = self._l0_store.append_execution_pending_turn_sync(
                session_id=session_id,
                run_id=active_run.run_id,
                turn_id=turn_id,
                content=content,
                revision=active_run.revision,
                disposition=disposition,
            )
            pending_turn = self._to_pending_turn(pending_payload)
            logger.info(
                "Chat session run queued pending turn",
                session_id=session_id,
                run_id=active_run.run_id,
                revision=active_run.revision,
                turn_id=pending_turn.turn_id,
                disposition=pending_turn.disposition,
            )
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
                cancel_requested_at=None,
                cancel_reason=None,
                cancel_requested_by=None,
                cancel_anchor_turn_id=None,
            )
            self._push_root_goal(
                session_id=session_id,
                run_id=active_run.run_id,
                revision=active_run.revision,
                root_user_message=content,
            )
            active_run = self._require_run(session_id)
            logger.info(
                "Chat session run root turn updated",
                session_id=session_id,
                run_id=active_run.run_id,
                revision=active_run.revision,
                root_turn_id=active_run.root_turn_id,
            )
            return deepcopy(active_run)

    def complete_active_run(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> bool:
        """Clear the active run when the expected run/revision is still current."""
        with self._lock:
            active_run = self._get_run(session_id)
            if active_run is None:
                return False
            if run_id is not None and active_run.run_id != run_id:
                return False
            if revision is not None and active_run.revision != int(revision):
                return False
            self._complete_root_goal(session_id=session_id, active_run=active_run)
            self._l0_store.clear_execution_state_sync(session_id)
            logger.info(
                "Chat session run completed",
                session_id=session_id,
                run_id=active_run.run_id,
                revision=active_run.revision,
            )
            return True

    def request_cancel(
        self,
        session_id: str,
        *,
        requested_by: str,
        reason: str = "user_cancel",
        anchor_turn_id: str | None = None,
    ) -> ActiveRun:
        """Mark the active run as cancelling and persist cancel metadata."""
        with self._lock:
            active_run = self._require_run(session_id)
            self._l0_store.upsert_execution_run_sync(
                session_id=session_id,
                run_id=active_run.run_id,
                status="cancelling",
                revision=active_run.revision,
                root_turn_id=active_run.root_turn_id,
                root_user_message=active_run.root_user_message,
                response_anchor_turn_id=active_run.root_turn_id,
                cancel_requested_at=time(),
                cancel_reason=reason,
                cancel_requested_by=requested_by,
                cancel_anchor_turn_id=anchor_turn_id,
            )
            active_run = self._require_run(session_id)
            logger.info(
                "Chat session run cancelling",
                session_id=session_id,
                run_id=active_run.run_id,
                revision=active_run.revision,
                cancel_requested_by=active_run.cancel_requested_by,
                cancel_reason=active_run.cancel_reason,
                cancel_anchor_turn_id=active_run.cancel_anchor_turn_id,
            )
            return deepcopy(active_run)

    def mark_cancelled(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> ActiveRun:
        """Transition the active run from cancelling to cancelled."""
        with self._lock:
            active_run = self._require_run(session_id)
            if run_id is not None and active_run.run_id != run_id:
                raise ValueError(f"Active run mismatch for session_id={session_id!r}")
            if revision is not None and active_run.revision != int(revision):
                raise ValueError(f"Active revision mismatch for session_id={session_id!r}")
            self._l0_store.upsert_execution_run_sync(
                session_id=session_id,
                run_id=active_run.run_id,
                status="cancelled",
                revision=active_run.revision,
                root_turn_id=active_run.root_turn_id,
                root_user_message=active_run.root_user_message,
                response_anchor_turn_id=active_run.root_turn_id,
                cancel_requested_at=active_run.cancel_requested_at,
                cancel_reason=active_run.cancel_reason,
                cancel_requested_by=active_run.cancel_requested_by,
                cancel_anchor_turn_id=active_run.cancel_anchor_turn_id,
            )
            self._cancel_root_goal(
                session_id=session_id,
                active_run=active_run,
                reason="Cancelled before completion",
            )
            active_run = self._require_run(session_id)
            logger.info(
                "Chat session run cancelled",
                session_id=session_id,
                run_id=active_run.run_id,
                revision=active_run.revision,
            )
            return deepcopy(active_run)

    def consume_pending_turns(
        self,
        session_id: str,
        *,
        revision: int | None = None,
        disposition: str | None = None,
    ) -> list[PendingTurn]:
        """Return and clear pending turns for the active run.

        When ``disposition`` is provided, only turns matching both the revision
        (if given) and the disposition are removed; remaining turns stay
        queued. This lets AUGMENT and DEFER queues be drained independently.
        """
        with self._lock:
            self._require_run(session_id)
            pending_turns = [
                self._to_pending_turn(item)
                for item in self._l0_store.consume_execution_pending_turns_sync(
                    session_id,
                    revision=revision,
                    disposition=disposition,
                )
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
            self._cancel_root_goal(
                session_id=session_id,
                active_run=active_run,
                reason="Superseded by a newer user turn",
            )
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
            logger.info(
                "Chat session run revised",
                session_id=session_id,
                run_id=active_run.run_id,
                revision=active_run.revision,
                clear_pending_turns=clear_pending_turns,
            )
            return deepcopy(active_run)

    @staticmethod
    def _goal_id(*, run_id: str, revision: int) -> str:
        return f"chat_run:{run_id}:{int(revision)}"

    def _push_root_goal(
        self,
        *,
        session_id: str,
        run_id: str,
        revision: int,
        root_user_message: str,
    ) -> None:
        description = str(root_user_message or "").strip()
        if not description:
            return
        self._l0_store.push_goal_sync(
            session_id=session_id,
            goal_id=self._goal_id(run_id=run_id, revision=revision),
            goal_type="chat_run",
            description=description,
            status="in_progress",
            priority=0,
            metadata={"run_id": run_id, "revision": int(revision)},
        )

    def _cancel_root_goal(
        self,
        *,
        session_id: str,
        active_run: ActiveRun,
        reason: str,
    ) -> None:
        self._l0_store.set_goal_status_sync(
            session_id=session_id,
            goal_id=self._goal_id(run_id=active_run.run_id, revision=active_run.revision),
            status="cancelled",
            result_summary=reason,
        )

    def _complete_root_goal(
        self,
        *,
        session_id: str,
        active_run: ActiveRun,
    ) -> None:
        self._l0_store.set_goal_status_sync(
            session_id=session_id,
            goal_id=self._goal_id(run_id=active_run.run_id, revision=active_run.revision),
            status="completed",
            result_summary="Chat run completed",
        )

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

    def _get_run(self, session_id: str) -> ActiveRun | None:
        state = self._l0_store.get_execution_state_sync(session_id)
        run = state.get("run")
        if not isinstance(run, dict):
            return None
        return ActiveRun(
            session_id=str(run["session_id"]),
            run_id=str(run["run_id"]),
            status=str(run.get("status") or "running"),
            root_turn_id=str(run["root_turn_id"]) if run.get("root_turn_id") is not None else None,
            root_user_message=str(run.get("root_user_message") or ""),
            revision=int(run.get("revision") or 0),
            cancel_requested_at=(
                float(run["cancel_requested_at"])
                if run.get("cancel_requested_at") is not None
                else None
            ),
            cancel_reason=str(run["cancel_reason"]) if run.get("cancel_reason") is not None else None,
            cancel_requested_by=(
                str(run["cancel_requested_by"])
                if run.get("cancel_requested_by") is not None
                else None
            ),
            cancel_anchor_turn_id=(
                str(run["cancel_anchor_turn_id"])
                if run.get("cancel_anchor_turn_id") is not None
                else None
            ),
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
        disposition = str(payload.get("disposition") or "augment").strip().lower()
        if disposition not in {"augment", "defer"}:
            disposition = "augment"
        return PendingTurn(
            turn_id=str(payload["turn_id"]),
            content=str(payload["content"]),
            revision=int(payload["revision"]),
            disposition=disposition,
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
