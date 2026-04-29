"""Session-scoped execution coordination for chat task-agent turns."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from ....agent.run_control import DetachSignal
from ....agent.runtime.contracts import FactRecord
from ..common import IncomingFactKind, TaskFactPayload, UserMessagePayload
from .fact_classifier import ClassifiedFact
from .interruption_classifier import (
    InterruptionClassifier,
    InterruptionContext,
    InterruptionDisposition,
    StepState,
)
from .run_contracts import ActiveRun, RunResult, RunResultDisposition
from .session_run_decisions import CheckpointDecision, SessionFactDecision, TurnSupersession
from .session_turn_queue import SessionRunTurnQueueMixin
from .run_store import SessionRunStore

_CHECKPOINT_EVENT_TYPES = {"CHAT_TOOL_LOOP_STEP"}


class SessionRunCoordinator(SessionRunTurnQueueMixin):
    """Own session-scoped active run state and interjection handling."""

    def __init__(
        self,
        *,
        run_store: SessionRunStore | None = None,
        interruption_classifier: InterruptionClassifier | None = None,
    ) -> None:
        self._run_store = run_store or SessionRunStore()
        self._interruption_classifier = interruption_classifier or InterruptionClassifier()
        self._detach_signals: dict[str, DetachSignal] = {}

    def coordinate(self, classified_fact: ClassifiedFact) -> SessionFactDecision:
        """Resolve the visible fact and session-run state for one batch."""
        return self.route(classified_fact)

    def route(self, classified_fact: ClassifiedFact) -> SessionFactDecision:
        """Resolve the planner-facing fact for one classified batch."""
        active_run = self._run_store.get_active_run(classified_fact.session_id)
        if classified_fact.latest_user_payload is not None:
            return self.handle_user_turn(
                classified_fact.latest_user_payload,
                source_fact=classified_fact.latest_user_fact,
            )

        result_record = self._record_classified_result(
            classified_fact=classified_fact,
            active_run=active_run,
        )
        if result_record is not None and result_record.disposition == RunResultDisposition.STALE:
            refreshed_run = self._run_store.get_active_run(classified_fact.session_id)
            return SessionFactDecision(
                active_run=refreshed_run,
                planner_fact=classified_fact.latest_result_fact,
                planner_fact_kind=IncomingFactKind.OTHER_FACT,
                planner_user_message=(
                    refreshed_run.root_user_message
                    if refreshed_run is not None
                    else classified_fact.user_message
                ),
                latest_payload=classified_fact.latest_payload,
                user_id=classified_fact.user_id,
                session_id=classified_fact.session_id,
            )

        if (
            classified_fact.latest_result_fact is not None
            and active_run is not None
            and classified_fact.latest_result_fact.event_type in _CHECKPOINT_EVENT_TYPES
            and self._current_revision_augment_pending_turns(active_run)
        ):
            checkpoint_pending_turns = self._run_store.consume_pending_turns(
                classified_fact.session_id,
                revision=active_run.revision,
                disposition=InterruptionDisposition.AUGMENT.value,
            )
            refreshed_run = self._run_store.get_active_run(classified_fact.session_id)
            planner_user_message = self._merge_visible_user_message(
                root_user_message=active_run.root_user_message,
                pending_turns=checkpoint_pending_turns,
            )
            anchor_turn_id = checkpoint_pending_turns[-1].turn_id if checkpoint_pending_turns else active_run.root_turn_id
            return SessionFactDecision(
                active_run=refreshed_run,
                planner_fact=classified_fact.latest_result_fact,
                planner_fact_kind=IncomingFactKind.USER_MESSAGE,
                planner_user_message=planner_user_message,
                latest_payload=UserMessagePayload(
                    user_id=classified_fact.user_id,
                    session_id=classified_fact.session_id,
                    content=planner_user_message,
                    turn_id=anchor_turn_id,
                ),
                user_id=classified_fact.user_id,
                session_id=classified_fact.session_id,
                run_disposition=InterruptionDisposition.AUGMENT.value,
                checkpoint_pending_turns=checkpoint_pending_turns,
                superseded_turns=self._build_augment_supersessions(
                    root_turn_id=active_run.root_turn_id,
                    pending_turns=checkpoint_pending_turns,
                    anchor_turn_id=anchor_turn_id,
                ),
            )

        return SessionFactDecision(
            active_run=active_run,
            planner_fact=classified_fact.source_fact,
            planner_fact_kind=classified_fact.kind,
            planner_user_message=classified_fact.user_message,
            latest_payload=classified_fact.source_payload,
            user_id=classified_fact.user_id,
            session_id=classified_fact.session_id,
        )

    async def aroute(self, classified_fact: ClassifiedFact) -> SessionFactDecision:
        """Async variant that can use a model-backed interruption classifier."""
        active_run = self._run_store.get_active_run(classified_fact.session_id)
        if classified_fact.latest_user_payload is not None:
            return await self.ahandle_user_turn(
                classified_fact.latest_user_payload,
                source_fact=classified_fact.latest_user_fact,
            )

        result_record = self._record_classified_result(
            classified_fact=classified_fact,
            active_run=active_run,
        )
        if result_record is not None and result_record.disposition == RunResultDisposition.STALE:
            refreshed_run = self._run_store.get_active_run(classified_fact.session_id)
            return SessionFactDecision(
                active_run=refreshed_run,
                planner_fact=classified_fact.latest_result_fact,
                planner_fact_kind=IncomingFactKind.OTHER_FACT,
                planner_user_message=(
                    refreshed_run.root_user_message
                    if refreshed_run is not None
                    else classified_fact.user_message
                ),
                latest_payload=classified_fact.latest_payload,
                user_id=classified_fact.user_id,
                session_id=classified_fact.session_id,
            )

        if (
            classified_fact.latest_result_fact is not None
            and active_run is not None
            and classified_fact.latest_result_fact.event_type in _CHECKPOINT_EVENT_TYPES
            and self._current_revision_augment_pending_turns(active_run)
        ):
            checkpoint_pending_turns = self._run_store.consume_pending_turns(
                classified_fact.session_id,
                revision=active_run.revision,
                disposition=InterruptionDisposition.AUGMENT.value,
            )
            refreshed_run = self._run_store.get_active_run(classified_fact.session_id)
            planner_user_message = self._merge_visible_user_message(
                root_user_message=active_run.root_user_message,
                pending_turns=checkpoint_pending_turns,
            )
            anchor_turn_id = checkpoint_pending_turns[-1].turn_id if checkpoint_pending_turns else active_run.root_turn_id
            return SessionFactDecision(
                active_run=refreshed_run,
                planner_fact=classified_fact.latest_result_fact,
                planner_fact_kind=IncomingFactKind.USER_MESSAGE,
                planner_user_message=planner_user_message,
                latest_payload=UserMessagePayload(
                    user_id=classified_fact.user_id,
                    session_id=classified_fact.session_id,
                    content=planner_user_message,
                    turn_id=anchor_turn_id,
                ),
                user_id=classified_fact.user_id,
                session_id=classified_fact.session_id,
                run_disposition=InterruptionDisposition.AUGMENT.value,
                checkpoint_pending_turns=checkpoint_pending_turns,
                superseded_turns=self._build_augment_supersessions(
                    root_turn_id=active_run.root_turn_id,
                    pending_turns=checkpoint_pending_turns,
                    anchor_turn_id=anchor_turn_id,
                ),
            )

        return SessionFactDecision(
            active_run=active_run,
            planner_fact=classified_fact.source_fact,
            planner_fact_kind=classified_fact.kind,
            planner_user_message=classified_fact.user_message,
            latest_payload=classified_fact.source_payload,
            user_id=classified_fact.user_id,
            session_id=classified_fact.session_id,
        )

    def handle_user_turn(
        self,
        payload: UserMessagePayload,
        *,
        source_fact: FactRecord | None = None,
        step_state: StepState | None = None,
    ) -> SessionFactDecision:
        """Apply a user turn to the session run and return the visible decision."""
        active_run = self._run_store.get_active_run(payload.session_id)
        turn_id = self._resolve_turn_id(payload=payload, source_fact=source_fact)
        if active_run is None or active_run.status == "cancelled":
            active_run = self._run_store.create_active_run(
                payload.session_id,
                root_turn_id=turn_id,
                root_user_message=payload.content,
            )
            return SessionFactDecision(
                active_run=active_run,
                planner_fact=source_fact,
                planner_fact_kind=IncomingFactKind.USER_MESSAGE,
                planner_user_message=payload.content,
                latest_payload=payload,
                user_id=payload.user_id,
                session_id=payload.session_id,
                run_disposition="root",
            )

        disposition = self._interruption_classifier.classify(
            InterruptionContext(
                user_text=payload.content,
                step_state=step_state or StepState(),
            )
        )
        if disposition == InterruptionDisposition.INTERRUPT:
            superseded_turns = self._build_interrupt_supersessions(active_run=active_run, anchor_turn_id=turn_id)
            active_run = self._run_store.bump_revision(
                payload.session_id,
                clear_pending_turns=True,
            )
            active_run = self._run_store.set_root_turn(
                payload.session_id,
                turn_id=turn_id,
                content=payload.content,
            )
            planner_fact_kind = IncomingFactKind.USER_MESSAGE
        else:
            self._run_store.append_pending_turn(
                payload.session_id,
                turn_id,
                payload.content,
                disposition=(
                    disposition.value
                    if isinstance(disposition, InterruptionDisposition)
                    else InterruptionDisposition.AUGMENT.value
                ),
            )
            active_run = self._run_store.get_active_run(payload.session_id)
            planner_fact_kind = IncomingFactKind.OTHER_FACT
            superseded_turns = []
        return SessionFactDecision(
            active_run=active_run,
            planner_fact=source_fact,
            planner_fact_kind=planner_fact_kind,
            planner_user_message=payload.content,
            latest_payload=payload,
            user_id=payload.user_id,
            session_id=payload.session_id,
            run_disposition=(
                disposition.value if isinstance(disposition, InterruptionDisposition) else None
            ),
            interruption_disposition=disposition,
            checkpoint_pending_turns=self._current_revision_pending_turns(active_run),
            superseded_turns=superseded_turns,
        )

    async def ahandle_user_turn(
        self,
        payload: UserMessagePayload,
        *,
        source_fact: FactRecord | None = None,
        step_state: StepState | None = None,
    ) -> SessionFactDecision:
        """Async variant that can call the model-backed interruption classifier."""
        active_run = self._run_store.get_active_run(payload.session_id)
        turn_id = self._resolve_turn_id(payload=payload, source_fact=source_fact)
        if active_run is None or active_run.status == "cancelled":
            active_run = self._run_store.create_active_run(
                payload.session_id,
                root_turn_id=turn_id,
                root_user_message=payload.content,
            )
            return SessionFactDecision(
                active_run=active_run,
                planner_fact=source_fact,
                planner_fact_kind=IncomingFactKind.USER_MESSAGE,
                planner_user_message=payload.content,
                latest_payload=payload,
                user_id=payload.user_id,
                session_id=payload.session_id,
                run_disposition="root",
            )

        disposition = await self._interruption_classifier.aclassify(
            InterruptionContext(
                user_text=payload.content,
                root_user_message=active_run.root_user_message,
                pending_turns=[item.content for item in self._current_revision_pending_turns(active_run)],
                step_state=step_state or StepState(),
            )
        )
        if disposition == InterruptionDisposition.INTERRUPT:
            superseded_turns = self._build_interrupt_supersessions(active_run=active_run, anchor_turn_id=turn_id)
            active_run = self._run_store.bump_revision(
                payload.session_id,
                clear_pending_turns=True,
            )
            active_run = self._run_store.set_root_turn(
                payload.session_id,
                turn_id=turn_id,
                content=payload.content,
            )
            planner_fact_kind = IncomingFactKind.USER_MESSAGE
        else:
            self._run_store.append_pending_turn(
                payload.session_id,
                turn_id,
                payload.content,
                disposition=(
                    disposition.value
                    if isinstance(disposition, InterruptionDisposition)
                    else InterruptionDisposition.AUGMENT.value
                ),
            )
            active_run = self._run_store.get_active_run(payload.session_id)
            planner_fact_kind = IncomingFactKind.OTHER_FACT
            superseded_turns = []
        return SessionFactDecision(
            active_run=active_run,
            planner_fact=source_fact,
            planner_fact_kind=planner_fact_kind,
            planner_user_message=payload.content,
            latest_payload=payload,
            user_id=payload.user_id,
            session_id=payload.session_id,
            run_disposition=(
                disposition.value if isinstance(disposition, InterruptionDisposition) else None
            ),
            interruption_disposition=disposition,
            checkpoint_pending_turns=self._current_revision_pending_turns(active_run),
            superseded_turns=superseded_turns,
        )

    def get_active_run(self, session_id: str) -> ActiveRun | None:
        """Return the current active run for one session."""
        return self._run_store.get_active_run(session_id)

    def get_run_status(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> str | None:
        """Return the current status for the requested session run."""
        active_run = self._run_store.get_active_run(session_id)
        if active_run is None:
            return None
        if run_id is not None and active_run.run_id != run_id:
            return None
        if revision is not None and active_run.revision != int(revision):
            return None
        return active_run.status

    def request_cancel(
        self,
        *,
        session_id: str,
        requested_by: str,
        reason: str = "user_cancel",
        anchor_turn_id: str | None = None,
    ) -> ActiveRun | None:
        """Mark the active run as cancelling when one exists."""
        active_run = self._run_store.get_active_run(session_id)
        if active_run is None:
            return None
        return self._run_store.request_cancel(
            session_id,
            requested_by=requested_by,
            reason=reason,
            anchor_turn_id=anchor_turn_id,
        )

    def record_result(
        self,
        *,
        session_id: str,
        run_id: str,
        result_id: str,
        revision: int,
        payload: dict[str, Any],
    ) -> RunResult:
        """Apply revision barriers to one internal result."""
        return self._run_store.record_result(
            session_id=session_id,
            run_id=run_id,
            result_id=result_id,
            revision=revision,
            payload=payload,
        )

    def complete_run(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
        revision: int | None = None,
    ) -> bool:
        """Complete the active run if it still matches the expected identity."""
        active_run = self._run_store.get_active_run(session_id)
        if active_run is None:
            return False
        if run_id is not None and active_run.run_id != run_id:
            return False
        if revision is not None and active_run.revision != int(revision):
            return False
        if active_run.status == "cancelling":
            self._run_store.mark_cancelled(
                session_id,
                run_id=run_id,
                revision=revision,
            )
            return True
        if active_run.status == "cancelled":
            return True
        return self._run_store.complete_active_run(
            session_id,
            run_id=run_id,
            revision=revision,
        )

    def _record_classified_result(
        self,
        *,
        classified_fact: ClassifiedFact,
        active_run: ActiveRun | None,
    ) -> RunResult | None:
        result_fact = classified_fact.latest_result_fact
        if active_run is None or not isinstance(result_fact, FactRecord):
            return None
        if not isinstance(result_fact.payload, dict):
            return None
        run_id = str(result_fact.payload.get("run_id") or "").strip()
        if not run_id:
            return None
        try:
            revision = int(result_fact.payload.get("run_revision"))
        except (TypeError, ValueError):
            return None
        result_id = str(result_fact.correlation_id or result_fact.event_id or uuid4().hex)
        return self.record_result(
            session_id=classified_fact.session_id,
            run_id=run_id,
            result_id=result_id,
            revision=revision,
            payload=dict(result_fact.payload),
        )

    def _resolve_turn_id(
        self,
        *,
        payload: UserMessagePayload,
        source_fact: FactRecord | None,
    ) -> str:
        if payload.turn_id:
            return payload.turn_id
        if isinstance(source_fact, FactRecord) and source_fact.correlation_id:
            return source_fact.correlation_id
        return uuid4().hex
