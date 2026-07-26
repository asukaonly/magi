"""Lifecycle operations for chat session runs."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from time import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from magi_plugin_sdk.run_trigger import RunTrigger

from magi.core.logger import get_logger
from magi.control.run_control import RunControl
from magi.agent.task_agents.handlers.run_contracts import AgentRun, ActiveRun, PendingTurn

if TYPE_CHECKING:
    from magi.agent.run.snapshot import RunSnapshot

logger = get_logger(__name__)


class SessionRunLifecycleMixin:
    """Create, update, cancel, and complete active chat session runs."""

    _lock: RLock
    _execution_store: Any
    _workbench_store: Any
    _run_controls: "dict[tuple[str, str], RunControl]"
    _run_snapshots: "dict[tuple[str, str], RunSnapshot]"

    def create_active_run(
        self,
        session_id: str,
        *,
        root_turn_id: str | None = None,
        root_user_message: str = "",
        run_id: str | None = None,
        trigger: RunTrigger | None = None,
    ) -> ActiveRun:
        """Create or replace the active run for a session.

        The optional typed trigger describes what initiated the live run.
        Restart recovery reconstructs it from the durable delivery envelope
        when the logical turn is redriven.
        """
        with self._lock:
            self._execution_store.clear_execution_state_sync(session_id)
            run_identifier = run_id or uuid4().hex
            self._execution_store.upsert_execution_run_sync(
                session_id=session_id,
                run_id=run_identifier,
                status="running",
                revision=0,
                root_turn_id=root_turn_id,
                root_user_message=root_user_message,
                response_anchor_turn_id=root_turn_id,
                trigger_dict=trigger.to_dict() if trigger is not None else None,
            )
            self._discard_session_run_controls(session_id)
            self._push_root_goal(
                session_id=session_id,
                run_id=run_identifier,
                revision=0,
                root_turn_id=root_turn_id,
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
            pending_payload = self._execution_store.append_execution_pending_turn_sync(
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
            self._execution_store.upsert_execution_run_sync(
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
            self._discard_session_run_controls(session_id)
            self._push_root_goal(
                session_id=session_id,
                run_id=active_run.run_id,
                revision=active_run.revision,
                root_turn_id=turn_id,
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
        completed, _ = self.complete_active_run_with_deferred(
            session_id,
            run_id=run_id,
            revision=revision,
        )
        return completed

    def complete_active_run_with_deferred(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> tuple[bool, list[PendingTurn]]:
        """Complete one exact run and atomically return its DEFER turns."""

        with self._lock:
            active_run = self._get_run(session_id)
            if active_run is None:
                return False, []
            if run_id is not None and active_run.run_id != run_id:
                return False, []
            if revision is not None and active_run.revision != int(revision):
                return False, []
            deferred_turns = [
                self._to_pending_turn(item)
                for item in self._execution_store.get_execution_state_sync(
                    session_id
                ).get("pending_turns", [])
                if int(item.get("revision") or 0) == active_run.revision
                and str(item.get("disposition") or "").strip().lower()
                == "defer"
            ]
            if active_run.status == "cancelling":
                self.mark_cancelled(
                    session_id,
                    run_id=active_run.run_id,
                    revision=active_run.revision,
                )
                self._execution_store.consume_execution_pending_turns_sync(
                    session_id,
                    revision=active_run.revision,
                    disposition="defer",
                )
                self._discard_exact_run_control(
                    session_id=session_id,
                    run_id=active_run.run_id,
                )
                return True, deferred_turns
            if active_run.status == "cancelled":
                self._execution_store.consume_execution_pending_turns_sync(
                    session_id,
                    revision=active_run.revision,
                    disposition="defer",
                )
                self._discard_exact_run_control(
                    session_id=session_id,
                    run_id=active_run.run_id,
                )
                return True, deferred_turns
            self._complete_root_goal(session_id=session_id, active_run=active_run)
            self._execution_store.clear_execution_state_sync(session_id)
            self._discard_exact_run_control(
                session_id=session_id,
                run_id=active_run.run_id,
            )
            logger.info(
                "Chat session run completed",
                session_id=session_id,
                run_id=active_run.run_id,
                revision=active_run.revision,
            )
            return True, deferred_turns

    def request_cancel(
        self,
        session_id: str,
        *,
        requested_by: str,
        reason: str = "user_cancel",
        anchor_turn_id: str | None = None,
    ) -> ActiveRun:
        """Mark the active run as cancelling and retain cancel metadata."""
        with self._lock:
            active_run = self._require_run(session_id)
            self._execution_store.upsert_execution_run_sync(
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
            self._execution_store.upsert_execution_run_sync(
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
        """Return and clear pending turns for the active run."""
        with self._lock:
            self._require_run(session_id)
            pending_turns = [
                self._to_pending_turn(item)
                for item in self._execution_store.consume_execution_pending_turns_sync(
                    session_id,
                    revision=revision,
                    disposition=disposition,
                )
            ]
            return pending_turns

    def discard_pending_turn(
        self,
        session_id: str,
        *,
        turn_id: str,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> PendingTurn | None:
        """Remove one exact pending turn without changing its active root run."""

        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("turn_id must not be empty")
        with self._lock:
            active_run = self._get_run(session_id)
            if active_run is None:
                return None
            normalized_run_id = str(run_id or "").strip()
            if normalized_run_id and active_run.run_id != normalized_run_id:
                return None
            if revision is not None and active_run.revision != int(revision):
                return None
            removed = self._execution_store.consume_execution_pending_turns_sync(
                session_id,
                revision=active_run.revision,
                turn_id=normalized_turn_id,
            )
            if len(removed) != 1:
                return None
            return deepcopy(self._to_pending_turn(removed[0]))

    async def discard_pending_turn_for_delete(
        self,
        session_id: str,
        *,
        turn_id: str,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> PendingTurn | None:
        """Remove one pending turn and its optional workbench projection."""

        removed = self.discard_pending_turn(
            session_id,
            turn_id=turn_id,
            run_id=run_id,
            revision=revision,
        )
        if removed is None:
            return None
        self._execution_store.forget_execution_turn_sync(
            session_id=session_id,
            turn_id=turn_id,
        )
        if self._workbench_store is not None:
            await self._workbench_store.forget_chat_turn(
                session_id=session_id,
                turn_id=turn_id,
            )
        return removed

    def register_active_run_control(
        self,
        session_id: str,
        run_id: str,
        control: RunControl,
    ) -> None:
        """Bind a live RunControl bundle to the (session_id, run_id) pair.

        Called by ChatTaskAgent at turn start so external callers
        (SessionRunCoordinator.request_retract, eventual cancel/detach
        external APIs) can locate the bundle and fire its signals.

        The bundle contains asyncio Events and inboxes that cannot be
        persisted; the active run is therefore process-local too.
        """
        with self._lock:
            self._run_controls[(session_id, run_id)] = control

    def get_active_run_control(
        self,
        session_id: str,
        run_id: str,
    ) -> RunControl | None:
        """Return the live bundle for this run, or None if not registered.

        Callers must tolerate ``None`` while a run is being created or torn
        down.
        """
        with self._lock:
            return self._run_controls.get((session_id, run_id))

    def unregister_active_run_control(
        self,
        session_id: str,
        run_id: str,
    ) -> None:
        """Drop the binding for (session_id, run_id). No-op if not registered.

        Called by ChatTaskAgent on terminal status so the dict does not
        accumulate stale references after runs complete. The bundle's
        asyncio.Events and inboxes are not persistable, so keeping a dead
        reference accomplishes nothing.
        """
        with self._lock:
            self._discard_exact_run_control(
                session_id=session_id,
                run_id=run_id,
            )

    def _discard_exact_run_control(
        self,
        *,
        session_id: str,
        run_id: str,
    ) -> None:
        """Drop only the runtime control owned by one exact run."""

        self._run_controls.pop((session_id, run_id), None)

    def _discard_session_run_controls(self, session_id: str) -> None:
        """Drop controls made obsolete when a session root is replaced."""

        stale_keys = [
            key for key in self._run_controls if key[0] == session_id
        ]
        for key in stale_keys:
            self._run_controls.pop(key, None)

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
                self._execution_store.consume_execution_pending_turns_sync(session_id)
            self._execution_store.upsert_execution_run_sync(
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
            self._discard_session_run_controls(session_id)
            active_run = self._require_run(session_id)
            logger.info(
                "Chat session run revised",
                session_id=session_id,
                run_id=active_run.run_id,
                revision=active_run.revision,
                clear_pending_turns=clear_pending_turns,
            )
            return deepcopy(active_run)

    def list_active_runs(self, session_id: str) -> list[AgentRun]:
        """Phase E: return the list of active runs for ``session_id``.

        Phase E scope: returns at most one run (single-active-run
        semantics preserved). Phase G/H enables real concurrent runs
        (multi-channel inbound); the API surface is established now so
        callers can be written against the list form.
        """
        single = self.get_active_run(session_id)
        return [single] if single is not None else []

    def single_active_run(self, session_id: str) -> AgentRun | None:
        """Convenience accessor: returns the first active run or None.

        Use this from callers that have not yet been migrated to handle
        multiple concurrent runs. New code should iterate
        ``list_active_runs`` directly.
        """
        runs = self.list_active_runs(session_id)
        return runs[0] if runs else None

    def save_run_snapshot(
        self,
        session_id: str,
        run_id: str,
        snapshot: "RunSnapshot",
    ) -> None:
        """Persist the snapshot for ``(session_id, run_id)``.

        Called by ChatTaskAgent (or the NodeSequenceRunner driver) after
        each node completes, so detach mid-sequence resumes from the
        latest snapshot. In-memory only — restart loses snapshots.
        Background-detached runs serialise the snapshot into
        ``BackgroundTaskSpec.initial_run_snapshot`` for cross-process
        survival.
        """
        with self._lock:
            self._run_snapshots[(session_id, run_id)] = snapshot

    def get_run_snapshot(
        self,
        session_id: str,
        run_id: str,
    ) -> "RunSnapshot | None":
        """Return the most recent snapshot for ``(session_id, run_id)``."""
        with self._lock:
            return self._run_snapshots.get((session_id, run_id))

    def clear_run_snapshot(
        self,
        session_id: str,
        run_id: str,
    ) -> None:
        """Drop the snapshot. No-op if not present."""
        with self._lock:
            self._run_snapshots.pop((session_id, run_id), None)


__all__ = ["SessionRunLifecycleMixin"]
