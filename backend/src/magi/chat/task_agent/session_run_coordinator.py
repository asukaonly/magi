"""Session-scoped execution coordination for chat task-agent turns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from magi_plugin_sdk.run_trigger import IncomingEvent

from magi.control.run_control import DetachSignal, RetractRequested
from magi.agent.runtime.contracts import FactRecord
from magi.core.logger import get_logger
from magi.agent.run_triggers import build_user_message_trigger, is_external_source
from magi.agent.task_agents.common import IncomingFactKind, UserMessagePayload
from magi.agent.task_agents.handlers.run_contracts import ActiveRun
from .fact_classifier import ClassifiedFact
from .interruption_classifier import (
    InterruptionClassifier,
    InterruptionContext,
    InterruptionDisposition,
    StepState,
)
from magi.agent.task_agents.handlers.run_contracts import RunResultDisposition
from .delivery_dispatch import ChatDeliveryDispatchPort
from .session_run_decisions import SessionFactDecision, TurnSupersession
from .session_run_lifecycle import SessionRunLifecycleMixin
from .session_turn_queue import SessionRunTurnQueueMixin
from .run_store import SessionRunStore

logger = get_logger(__name__)

_CHECKPOINT_EVENT_TYPES = {"CHAT_TOOL_LOOP_STEP"}

# Phase H+1 / ADR-0004 P3: source→RunTrigger classification moved to the
# trigger seam (``magi.agent.run_triggers``: build_user_message_trigger /
# is_external_source). External sources additionally produce an
# ``IncomingEvent(external_inbound)`` when landing on an already-active run.


@dataclass(slots=True)
class _AppliedUserTurnDisposition:
    active_run: ActiveRun | None
    planner_fact_kind: IncomingFactKind
    superseded_turns: list[TurnSupersession]


class SessionRunCoordinator(SessionRunLifecycleMixin, SessionRunTurnQueueMixin):
    """Own session-scoped active run state and interjection handling."""

    def __init__(
        self,
        *,
        run_store: SessionRunStore | None = None,
        interruption_classifier: InterruptionClassifier | None = None,
        delivery_dispatcher: ChatDeliveryDispatchPort | None = None,
        conversation_log: object | None = None,
    ) -> None:
        self._run_store = run_store or SessionRunStore()
        self._interruption_classifier = interruption_classifier or InterruptionClassifier()
        self._detach_signals: dict[str, DetachSignal] = {}
        self._delivery_dispatcher = delivery_dispatcher
        # Phase F Task 11: optional ConversationLog — when wired,
        # ``request_message_retract`` appends a message_redacted event
        # and propagates the redaction to every active dependent run via
        # the log's find_dependents → RetractSignal pipeline.
        self._conversation_log = conversation_log

    def request_retract(
        self,
        *,
        session_id: str,
        payload: RetractRequested | None = None,
    ) -> bool:
        """Request retract on the active run for ``session_id``.

        Looks up the active run, then its registered RunControl, then
        fires the bundle's ``retract_signal``. The execution path
        (DirectLLMHandler / FunctionCallingHandler / OrchestrationLaunchHandler)
        observes the signal on its next iteration boundary or LLM-stream
        chunk and returns a retracted outcome.

        Returns True if a live RunControl was found and signaled.
        Returns False when:
          - no active run exists for the session
          - active run exists but has no registered control (e.g., a
            background-restored run whose control was not bound)
        """
        active_run = self._run_store.get_active_run(session_id)
        if active_run is None:
            return False
        control = self._run_store.get_active_run_control(session_id, active_run.run_id)
        if control is None:
            return False
        control.retract_signal.request(payload)

        # Phase G+3: also retract messages that were already delivered
        # through external channels.
        if self._delivery_dispatcher is not None and session_id and active_run.run_id:
            import asyncio

            async def _retract_delivered_messages() -> None:
                try:
                    await self._delivery_dispatcher.retract_run_deliveries(
                        session_id=session_id,
                        run_id=active_run.run_id,
                    )
                except Exception:
                    logger.warning(
                        "delivery_dispatcher.retract_run_deliveries failed",
                        exc_info=True,
                    )

            # Schedule but don't block — retract on bundles is already async
            # via the cooperative signal.
            asyncio.create_task(_retract_delivered_messages())

        return True

    async def request_message_retract(
        self,
        *,
        session_id: str,
        message_id: str,
        actor: str = "system",
        payload: RetractRequested | None = None,
    ) -> bool:
        """Phase F Task 11: cross-run retract of a single message.

        Thin wrapper around the internal :meth:`_do_message_retract` so the
        same logic is reachable for callers (``ChatTaskAgent`` and tests).

        See :meth:`_do_message_retract` for the full pipeline contract.
        """
        return await self._do_message_retract(
            session_id=session_id,
            message_id=message_id,
            actor=actor,
            payload=payload,
        )

    async def _do_message_retract(
        self,
        *,
        session_id: str,
        message_id: str,
        actor: str = "system",
        payload: RetractRequested | None = None,
    ) -> bool:
        """Internal: actual cross-run retract work for a single message.

        Distinct from :meth:`request_retract` (which cancels the active
        run): this marks ONE message redacted in the ConversationLog and
        then propagates the retract to every dependent active run.

        Pipeline:
        1. Append a ``message_redacted`` event to the log — the log's
           ``append`` side effect flips ``is_visible=0`` on the target so
           subsequent materializations exclude it.
        2. Ask the log for the runs that consumed the target message_id
           via ``find_dependents``.
        3. For each dependent run, look up its registered RunControl and
           fire ``retract_signal``. Runs whose control is no longer
           registered (e.g., completed runs) are silently skipped — the
           active-run propagation is what carries the cross-run guarantee.

        Returns True if any active dependent run was signaled, False
        otherwise (no log wired, append failed, find_dependents failed,
        or no dependents to signal). Failures in the log calls are
        swallowed so a transient log outage cannot crash the caller.

        Called by ``request_message_retract`` (public entry point).
        """
        if self._conversation_log is None:
            return False
        if not await self._append_message_redaction_event(
            session_id=session_id,
            message_id=message_id,
            actor=actor,
        ):
            return False
        dependents = await self._find_message_dependents(
            session_id=session_id,
            message_id=message_id,
        )
        if dependents is None:
            return False
        return self._signal_dependent_retracts(
            session_id=session_id,
            dependents=dependents,
            payload=payload,
        )

    async def _append_message_redaction_event(
        self,
        *,
        session_id: str,
        message_id: str,
        actor: str,
    ) -> bool:
        try:
            await self._conversation_log.append(
                self._build_message_redacted_event(message_id=message_id, actor=actor),
                session_id=session_id,
            )
            return True
        except Exception:
            logger.warning("ConversationLog.append(message_redacted) failed", exc_info=True)
            return False

    @staticmethod
    def _build_message_redacted_event(*, message_id: str, actor: str) -> Any:
        import time
        import uuid

        from magi_plugin_sdk.conversation import ConversationEvent

        return ConversationEvent(
            event_id=uuid.uuid4().hex,
            event_type="message_redacted",
            timestamp_ms=int(time.time() * 1000),
            actor=actor,
            content=None,
            redacts=message_id,
        )

    async def _find_message_dependents(
        self,
        *,
        session_id: str,
        message_id: str,
    ) -> Any | None:
        try:
            return await self._conversation_log.find_dependents(
                session_id=session_id,
                message_id=message_id,
            )
        except Exception:
            logger.warning("ConversationLog.find_dependents failed", exc_info=True)
            return None

    def _signal_dependent_retracts(
        self,
        *,
        session_id: str,
        dependents: Any,
        payload: RetractRequested | None,
    ) -> bool:
        signaled = 0
        for dep_run_id, _dep_revision in dependents:
            control = self._run_store.get_active_run_control(session_id, dep_run_id)
            if control is None:
                # Completed-run propagation is intentionally a no-op in
                # this MVP — it would need schema changes to flag the
                # past snapshot as ``revision_invalidated``. The active
                # path covers the cross-run guarantee that matters most.
                continue
            try:
                control.retract_signal.request(payload)
                signaled += 1
            except Exception:
                logger.warning(
                    "RetractSignal.request failed for dependent run %s",
                    dep_run_id,
                    exc_info=True,
                )
        return signaled > 0

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
        return self._route_non_user_fact(classified_fact, active_run)

    async def aroute(self, classified_fact: ClassifiedFact) -> SessionFactDecision:
        """Async variant that can use a model-backed interruption classifier."""
        active_run = self._run_store.get_active_run(classified_fact.session_id)
        if classified_fact.latest_user_payload is not None:
            return await self.ahandle_user_turn(
                classified_fact.latest_user_payload,
                source_fact=classified_fact.latest_user_fact,
            )
        return self._route_non_user_fact(classified_fact, active_run)

    def _route_non_user_fact(
        self,
        classified_fact: ClassifiedFact,
        active_run: ActiveRun | None,
    ) -> SessionFactDecision:
        result_record = self._record_classified_result(
            classified_fact=classified_fact,
            active_run=active_run,
        )
        if result_record is not None and result_record.disposition == RunResultDisposition.STALE:
            return self._stale_result_decision(classified_fact)

        if self._should_consume_checkpoint_augment(classified_fact, active_run):
            return self._checkpoint_augment_decision(classified_fact, active_run)

        return self._default_route_decision(classified_fact, active_run)

    def _stale_result_decision(self, classified_fact: ClassifiedFact) -> SessionFactDecision:
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

    def _should_consume_checkpoint_augment(
        self,
        classified_fact: ClassifiedFact,
        active_run: ActiveRun | None,
    ) -> bool:
        return (
            classified_fact.latest_result_fact is not None
            and active_run is not None
            and classified_fact.latest_result_fact.event_type in _CHECKPOINT_EVENT_TYPES
            and bool(self._current_revision_augment_pending_turns(active_run))
        )

    def _checkpoint_augment_decision(
        self,
        classified_fact: ClassifiedFact,
        active_run: ActiveRun,
    ) -> SessionFactDecision:
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
        anchor_turn_id = (
            checkpoint_pending_turns[-1].turn_id
            if checkpoint_pending_turns
            else active_run.root_turn_id
        )
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

    @staticmethod
    def _default_route_decision(
        classified_fact: ClassifiedFact,
        active_run: ActiveRun | None,
    ) -> SessionFactDecision:
        return SessionFactDecision(
            active_run=active_run,
            planner_fact=classified_fact.source_fact,
            planner_fact_kind=classified_fact.kind,
            planner_user_message=classified_fact.user_message,
            latest_payload=classified_fact.source_payload,
            user_id=classified_fact.user_id,
            session_id=classified_fact.session_id,
        )

    @staticmethod
    def _build_external_inbound_event(
        *,
        payload: UserMessagePayload,
        active_run_id: str | None,
    ) -> IncomingEvent:
        """Phase H+1: build the ``IncomingEvent(external_inbound)`` queued
        alongside the legacy ``pending_turn`` when an external message
        lands on an already-active run.

        Kept as a helper so both the sync and async ``handle_user_turn``
        paths share one construction site.
        """
        import time
        import uuid

        return IncomingEvent(
            event_id=uuid.uuid4().hex,
            event_type="external_inbound",
            target_run_id=active_run_id,
            arrived_at_ms=int(time.time() * 1000),
            payload={
                "source_channel": payload.source,
                "content": payload.content,
                "user_id": payload.user_id,
            },
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
            return self._start_root_user_turn(
                payload=payload,
                turn_id=turn_id,
                source_fact=source_fact,
            )

        if payload.recall_feedback is not None:
            return self._finish_interrupted_user_turn(
                payload=payload,
                turn_id=turn_id,
                source_fact=source_fact,
                active_run=active_run,
                disposition=InterruptionDisposition.INTERRUPT,
            )

        disposition = self._interruption_classifier.classify(
            InterruptionContext(
                user_text=payload.content,
                step_state=step_state or StepState(),
            )
        )
        return self._finish_interrupted_user_turn(
            payload=payload,
            turn_id=turn_id,
            source_fact=source_fact,
            active_run=active_run,
            disposition=disposition,
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
            return self._start_root_user_turn(
                payload=payload,
                turn_id=turn_id,
                source_fact=source_fact,
            )

        if payload.recall_feedback is not None:
            return self._finish_interrupted_user_turn(
                payload=payload,
                turn_id=turn_id,
                source_fact=source_fact,
                active_run=active_run,
                disposition=InterruptionDisposition.INTERRUPT,
            )

        disposition = await self._interruption_classifier.aclassify(
            InterruptionContext(
                user_text=payload.content,
                root_user_message=active_run.root_user_message,
                pending_turns=[
                    item.content for item in self._current_revision_pending_turns(active_run)
                ],
                step_state=step_state or StepState(),
            )
        )
        return self._finish_interrupted_user_turn(
            payload=payload,
            turn_id=turn_id,
            source_fact=source_fact,
            active_run=active_run,
            disposition=disposition,
        )

    def _start_root_user_turn(
        self,
        *,
        payload: UserMessagePayload,
        turn_id: str,
        source_fact: FactRecord | None,
    ) -> SessionFactDecision:
        active_run = self._run_store.create_active_run(
            payload.session_id,
            root_turn_id=turn_id,
            root_user_message=payload.content,
            trigger=build_user_message_trigger(
                source=payload.source,
                requester=payload.user_id,
                content=payload.content,
                turn_id=turn_id,
            ),
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

    def _finish_interrupted_user_turn(
        self,
        *,
        payload: UserMessagePayload,
        turn_id: str,
        source_fact: FactRecord | None,
        active_run: ActiveRun,
        disposition: InterruptionDisposition,
    ) -> SessionFactDecision:
        applied = self._apply_user_turn_disposition(
            payload=payload,
            turn_id=turn_id,
            active_run=active_run,
            disposition=disposition,
        )
        self._append_external_inbound_event_if_needed(applied.active_run, payload)
        return SessionFactDecision(
            active_run=applied.active_run,
            planner_fact=source_fact,
            planner_fact_kind=applied.planner_fact_kind,
            planner_user_message=payload.content,
            latest_payload=payload,
            user_id=payload.user_id,
            session_id=payload.session_id,
            run_disposition=(
                disposition.value if isinstance(disposition, InterruptionDisposition) else None
            ),
            interruption_disposition=disposition,
            checkpoint_pending_turns=self._current_revision_pending_turns(applied.active_run),
            superseded_turns=applied.superseded_turns,
        )

    def _apply_user_turn_disposition(
        self,
        *,
        payload: UserMessagePayload,
        turn_id: str,
        active_run: ActiveRun,
        disposition: InterruptionDisposition,
    ) -> _AppliedUserTurnDisposition:
        if disposition == InterruptionDisposition.INTERRUPT:
            superseded_turns = self._build_interrupt_supersessions(
                active_run=active_run,
                anchor_turn_id=turn_id,
            )
            self._run_store.bump_revision(payload.session_id, clear_pending_turns=True)
            refreshed_run = self._run_store.set_root_turn(
                payload.session_id,
                turn_id=turn_id,
                content=payload.content,
            )
            return _AppliedUserTurnDisposition(
                active_run=refreshed_run,
                planner_fact_kind=IncomingFactKind.USER_MESSAGE,
                superseded_turns=superseded_turns,
            )

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
        return _AppliedUserTurnDisposition(
            active_run=self._run_store.get_active_run(payload.session_id),
            planner_fact_kind=IncomingFactKind.OTHER_FACT,
            superseded_turns=[],
        )

    def _append_external_inbound_event_if_needed(
        self,
        active_run: ActiveRun | None,
        payload: UserMessagePayload,
    ) -> None:
        if active_run is None or not is_external_source(payload.source):
            return
        active_run.pending_events.append(
            self._build_external_inbound_event(
                payload=payload,
                active_run_id=active_run.run_id,
            )
        )
