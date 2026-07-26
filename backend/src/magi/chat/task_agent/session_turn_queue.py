"""Pending-turn queues, detach signals, and supersession bookkeeping."""

from __future__ import annotations

from typing import TYPE_CHECKING

from magi_plugin_sdk.run_trigger import IncomingEvent

from magi.control.run_control import DetachRequested, DetachSignal
from .interruption_classifier import InterruptionDisposition
from magi.agent.task_agents.handlers.run_contracts import ActiveRun, PendingTurn
from .session_run_decisions import CheckpointDecision, TurnSupersession

if TYPE_CHECKING:
    from .run_store import SessionRunStore


# Phase H: IncomingEvent types that flow through the legacy PendingTurn-shaped
# queue. Other event types (user_retract, child_run_completed, ...) are
# handled by SessionRunCoordinator.dispatch_event.
_STEER_LIKE_EVENT_TYPES = frozenset({"user_steer", "user_augment"})


def _incoming_event_to_pending_turn(event: IncomingEvent) -> PendingTurn:
    """Project a steer-style IncomingEvent into the legacy PendingTurn shape
    so existing queue-consumption logic Just Works."""
    return PendingTurn(
        turn_id=event.event_id,
        content=str(event.payload.get("content") or ""),
        revision=int(event.payload.get("revision") or 0),
        disposition=str(event.payload.get("disposition") or InterruptionDisposition.AUGMENT.value),
        # PendingTurn.created_at is a float seconds; arrived_at_ms is ms.
        created_at=event.arrived_at_ms / 1000.0,
    )


class SessionRunTurnQueueMixin:
    """Queue and timeline helpers for :class:`SessionRunCoordinator`."""

    _run_store: "SessionRunStore"
    _detach_signals: dict[str, DetachSignal]

    def consume_checkpoint(self, session_id: str) -> CheckpointDecision:
        """Expose and clear AUGMENT pending turns at a checkpoint boundary."""
        active_run = self._run_store.get_active_run(session_id)
        if active_run is None:
            return CheckpointDecision(session_id=session_id, run_id="", revision=0)
        pending_turns = self._run_store.consume_pending_turns(
            session_id,
            revision=active_run.revision,
            disposition=InterruptionDisposition.AUGMENT.value,
        )
        visible_user_message = self._merge_visible_user_message(
            root_user_message=active_run.root_user_message,
            pending_turns=pending_turns,
        )
        refreshed_run = self._run_store.get_active_run(session_id)
        return CheckpointDecision(
            session_id=session_id,
            run_id=active_run.run_id,
            revision=refreshed_run.revision if refreshed_run is not None else active_run.revision,
            pending_turns=pending_turns,
            visible_user_message=visible_user_message,
        )

    def bind_detach_signal(self, session_id: str, signal: DetachSignal) -> None:
        """Expose the active run's detach signal for out-of-band user requests."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return
        self._detach_signals[normalized_session_id] = signal

    def release_detach_signal(
        self,
        session_id: str,
        signal: DetachSignal | None = None,
    ) -> None:
        """Drop the registered detach signal once the foreground run exits."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return
        current = self._detach_signals.get(normalized_session_id)
        if current is None:
            return
        if signal is not None and current is not signal:
            return
        self._detach_signals.pop(normalized_session_id, None)

    def request_detach(
        self,
        session_id: str,
        *,
        requested_by: str,
        reason: str = "user_detach",
        note: str = "",
    ) -> ActiveRun | None:
        """Request that the active run detach to background at the next boundary."""
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return None
        active_run = self._run_store.get_active_run(normalized_session_id)
        signal = self._detach_signals.get(normalized_session_id)
        if active_run is None or signal is None or active_run.status != "running":
            return None
        if not signal.is_requested():
            signal.request(
                DetachRequested(
                    reason=reason,
                    requested_by=requested_by,
                    note=note,
                )
            )
        return active_run

    def peek_steer_turns(
        self,
        session_id: str,
        *,
        revision: int | None = None,
    ) -> list[PendingTurn]:
        """Return STEER pending turns without removing them from the store."""
        active_run = self._run_store.get_active_run(session_id)
        if active_run is None:
            return []
        target_revision = active_run.revision if revision is None else int(revision)
        return [
            pending_turn
            for pending_turn in active_run.pending_turns
            if pending_turn.revision == target_revision
            and pending_turn.disposition == InterruptionDisposition.STEER.value
        ]

    def consume_steer_turns(
        self,
        session_id: str,
        *,
        revision: int | None = None,
    ) -> list[PendingTurn]:
        """Pop STEER pending turns queued on the active run."""
        active_run = self._run_store.get_active_run(session_id)
        if active_run is None:
            return []
        target_revision = active_run.revision if revision is None else int(revision)
        return self._run_store.consume_pending_turns(
            session_id,
            revision=target_revision,
            disposition=InterruptionDisposition.STEER.value,
        )

    async def discard_pending_turn_for_message_delete(
        self,
        *,
        session_id: str,
        turn_id: str,
        run_id: str | None,
        revision: int | None,
    ) -> PendingTurn | None:
        """Detach one exact unconsumed user turn from its active root run."""

        return await self._run_store.discard_pending_turn_for_delete(
            session_id,
            turn_id=turn_id,
            run_id=run_id,
            revision=revision,
        )

    def _merge_visible_user_message(
        self,
        *,
        root_user_message: str,
        pending_turns: list[PendingTurn],
    ) -> str:
        messages = [root_user_message.strip()] if root_user_message.strip() else []
        messages.extend(turn.content.strip() for turn in pending_turns if turn.content.strip())
        return "\n\n".join(messages)

    @staticmethod
    def _current_revision_pending_turns(active_run: ActiveRun | None) -> list[PendingTurn]:
        if active_run is None:
            return []
        items: list[PendingTurn] = [
            pending_turn
            for pending_turn in active_run.pending_turns
            if pending_turn.revision == active_run.revision
        ]
        # Phase H: also surface steer-style IncomingEvents that were dropped
        # onto active_run.pending_events by SessionRunCoordinator.dispatch_event.
        for event in active_run.pending_events:
            if event.event_type not in _STEER_LIKE_EVENT_TYPES:
                continue
            projected = _incoming_event_to_pending_turn(event)
            if projected.revision == active_run.revision:
                items.append(projected)
        return items

    @staticmethod
    def _current_revision_augment_pending_turns(active_run: ActiveRun | None) -> list[PendingTurn]:
        if active_run is None:
            return []
        return [
            pending_turn
            for pending_turn in active_run.pending_turns
            if pending_turn.revision == active_run.revision
            and pending_turn.disposition == InterruptionDisposition.AUGMENT.value
        ]

    @staticmethod
    def _current_revision_steer_pending_turns(active_run: ActiveRun | None) -> list[PendingTurn]:
        if active_run is None:
            return []
        return [
            pending_turn
            for pending_turn in active_run.pending_turns
            if pending_turn.revision == active_run.revision
            and pending_turn.disposition == InterruptionDisposition.STEER.value
        ]

    @staticmethod
    def _build_augment_supersessions(
        *,
        root_turn_id: str | None,
        pending_turns: list[PendingTurn],
        anchor_turn_id: str | None,
    ) -> list[TurnSupersession]:
        return SessionRunTurnQueueMixin._build_merge_supersessions(
            root_turn_id=root_turn_id,
            pending_turns=pending_turns,
            anchor_turn_id=anchor_turn_id,
            reason=InterruptionDisposition.AUGMENT.value,
        )

    @staticmethod
    def _build_steer_supersessions(
        *,
        root_turn_id: str | None,
        pending_turns: list[PendingTurn],
        anchor_turn_id: str | None,
    ) -> list[TurnSupersession]:
        return SessionRunTurnQueueMixin._build_merge_supersessions(
            root_turn_id=root_turn_id,
            pending_turns=pending_turns,
            anchor_turn_id=anchor_turn_id,
            reason=InterruptionDisposition.STEER.value,
        )

    @staticmethod
    def _build_merge_supersessions(
        *,
        root_turn_id: str | None,
        pending_turns: list[PendingTurn],
        anchor_turn_id: str | None,
        reason: str,
    ) -> list[TurnSupersession]:
        normalized_anchor_turn_id = str(anchor_turn_id or "").strip()
        if not normalized_anchor_turn_id:
            return []
        superseded: list[TurnSupersession] = []
        seen_turn_ids: set[str] = set()
        normalized_root_turn_id = str(root_turn_id or "").strip()
        if normalized_root_turn_id and normalized_root_turn_id != normalized_anchor_turn_id:
            superseded.append(
                TurnSupersession(
                    turn_id=normalized_root_turn_id,
                    anchor_turn_id=normalized_anchor_turn_id,
                    reason=reason,
                )
            )
            seen_turn_ids.add(normalized_root_turn_id)
        for pending_turn in pending_turns[:-1]:
            turn_id = str(pending_turn.turn_id or "").strip()
            if not turn_id or turn_id == normalized_anchor_turn_id or turn_id in seen_turn_ids:
                continue
            superseded.append(
                TurnSupersession(
                    turn_id=turn_id,
                    anchor_turn_id=normalized_anchor_turn_id,
                    reason=reason,
                )
            )
            seen_turn_ids.add(turn_id)
        return superseded

    @staticmethod
    def _build_interrupt_supersessions(
        *,
        active_run: ActiveRun,
        anchor_turn_id: str | None,
    ) -> list[TurnSupersession]:
        normalized_anchor_turn_id = str(anchor_turn_id or "").strip()
        if not normalized_anchor_turn_id:
            return []
        superseded: list[TurnSupersession] = []
        seen_turn_ids: set[str] = set()
        normalized_root_turn_id = str(active_run.root_turn_id or "").strip()
        if normalized_root_turn_id and normalized_root_turn_id != normalized_anchor_turn_id:
            superseded.append(
                TurnSupersession(
                    turn_id=normalized_root_turn_id,
                    anchor_turn_id=normalized_anchor_turn_id,
                    reason=InterruptionDisposition.INTERRUPT.value,
                )
            )
            seen_turn_ids.add(normalized_root_turn_id)
        for pending_turn in active_run.pending_turns:
            turn_id = str(pending_turn.turn_id or "").strip()
            if not turn_id or turn_id == normalized_anchor_turn_id or turn_id in seen_turn_ids:
                continue
            superseded.append(
                TurnSupersession(
                    turn_id=turn_id,
                    anchor_turn_id=normalized_anchor_turn_id,
                    reason=InterruptionDisposition.INTERRUPT.value,
                )
            )
            seen_turn_ids.add(turn_id)
        return superseded
