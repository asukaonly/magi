"""Session-scoped execution coordination for chat task-agent turns."""
from __future__ import annotations

from magi_plugin_sdk.run_trigger import IncomingEvent, RunTrigger

from magi.control.run_control import DetachSignal, RetractRequested
from ....agent.runtime.contracts import FactRecord
from ....core.logger import get_logger
from ..common import IncomingFactKind, TaskFactPayload, UserMessagePayload
from .fact_classifier import ClassifiedFact
from .interruption_classifier import (
    InterruptionClassifier,
    InterruptionContext,
    InterruptionDisposition,
    StepState,
)
from .run_contracts import RunResultDisposition
from .session_run_decisions import CheckpointDecision, SessionFactDecision, TurnSupersession
from .session_run_lifecycle import SessionRunLifecycleMixin
from .session_turn_queue import SessionRunTurnQueueMixin
from .run_store import SessionRunStore

logger = get_logger(__name__)

_CHECKPOINT_EVENT_TYPES = {"CHAT_TOOL_LOOP_STEP"}

# Phase H+1: sources that originate from MAGI-native surfaces (chat HTTP
# /chat router, the chat UI's SSE stream, etc.) keep the legacy
# ``user_message`` trigger. Every other source (telegram, weixin, slack,
# ...) flips the resulting ``RunTrigger`` to ``external_inbound`` and
# additionally produces an ``IncomingEvent(external_inbound)`` when the
# message lands on an already-active run.
_MAGI_NATIVE_SOURCES = frozenset({"api", "magi-chat", "chat_sse"})


def _is_external_source(source: str | None) -> bool:
    """Phase H+1: classify a dispatcher ``source`` string.

    Treats empty/whitespace as native (matches the legacy default in
    :class:`UserMessagePayload`). Case-insensitive comparison so plugins
    using ``"Telegram"`` etc. still classify correctly.
    """
    normalized = (source or "api").strip().lower()
    if not normalized:
        return False
    return normalized not in _MAGI_NATIVE_SOURCES


class SessionRunCoordinator(SessionRunLifecycleMixin, SessionRunTurnQueueMixin):
    """Own session-scoped active run state and interjection handling."""

    def __init__(
        self,
        *,
        run_store: SessionRunStore | None = None,
        interruption_classifier: InterruptionClassifier | None = None,
        delivery_router: object | None = None,
        receipts_store: object | None = None,
        conversation_log: object | None = None,
    ) -> None:
        self._run_store = run_store or SessionRunStore()
        self._interruption_classifier = interruption_classifier or InterruptionClassifier()
        self._detach_signals: dict[str, DetachSignal] = {}
        # Phase G: optional DeliveryRouter — when supplied, request_retract
        # also retracts any delivered messages via the channels.
        self._delivery_router = delivery_router
        # Phase G+3: optional DeliveryReceiptsStore — the authoritative
        # source of per-turn DeliveryReceipts. ``request_retract`` reads
        # from this store (when wired) so it no longer depends on the
        # run snapshot carrying the receipt list.
        self._receipts_store = receipts_store
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

        # Phase G+3: also retract delivered messages via DeliveryRouter,
        # reading the receipts from the dedicated DeliveryReceiptsStore
        # rather than walking snapshot.node_states.
        if (
            self._delivery_router is not None
            and self._receipts_store is not None
            and session_id
            and active_run.run_id
        ):
            import asyncio

            async def _retract_via_store() -> None:
                try:
                    receipts = await self._receipts_store.list_receipts(
                        session_id=session_id,
                        run_id=active_run.run_id,
                    )
                except Exception:
                    logger.warning(
                        "DeliveryReceiptsStore.list_receipts failed",
                        exc_info=True,
                    )
                    return
                if not receipts:
                    return
                try:
                    await self._delivery_router.fanout_retract(receipts=receipts)
                except Exception:
                    logger.warning(
                        "DeliveryRouter.fanout_retract failed",
                        exc_info=True,
                    )

            # Schedule but don't block — retract on bundles is already async
            # via the cooperative signal.
            asyncio.create_task(_retract_via_store())

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

        Phase H Task 7: thin wrapper around the internal
        :meth:`_do_message_retract` so the same logic is reachable from
        ``dispatch_event(user_retract)``. Both entry points funnel into
        one implementation; we keep this public name for legacy callers
        (``ChatTaskAgent`` and tests) that pre-date the typed dispatcher.

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

        Called by:
        - ``request_message_retract`` (legacy public entry point)
        - ``dispatch_event(IncomingEvent(event_type="user_retract"))``
        """
        if self._conversation_log is None:
            return False
        import time
        import uuid
        from magi_plugin_sdk.conversation import ConversationEvent
        redact_event = ConversationEvent(
            event_id=uuid.uuid4().hex,
            event_type="message_redacted",
            timestamp_ms=int(time.time() * 1000),
            actor=actor,
            content=None,
            redacts=message_id,
        )
        try:
            await self._conversation_log.append(redact_event, session_id=session_id)
        except Exception:
            logger.warning(
                "ConversationLog.append(message_redacted) failed", exc_info=True,
            )
            return False
        try:
            deps = await self._conversation_log.find_dependents(
                session_id=session_id, message_id=message_id,
            )
        except Exception:
            logger.warning(
                "ConversationLog.find_dependents failed", exc_info=True,
            )
            return False
        signaled = 0
        for dep_run_id, _dep_revision in deps:
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

    async def dispatch_event(
        self,
        *,
        session_id: str,
        event: IncomingEvent,
    ) -> bool:
        """Phase H: typed dispatcher for IncomingEvents.

        Returns True when the event was handled (queued to the active run's
        pending_events, or routed to a sibling coordinator method).
        Returns False when the caller needs to take a follow-up action —
        e.g. starting a new run with ``trigger=external_inbound`` because
        no active run exists yet.
        """
        if event.event_type in {"user_steer", "user_augment"}:
            active_run = self._run_store.get_active_run(session_id)
            if active_run is None:
                return False
            active_run.pending_events.append(event)
            return True

        if event.event_type == "user_retract":
            message_id = str(event.payload.get("message_id") or "")
            if not message_id:
                logger.warning(
                    "user_retract event missing payload.message_id; skipping"
                )
                return False
            # Phase H Task 7: dispatch_event funnels into the same
            # private ``_do_message_retract`` that the public wrapper
            # ``request_message_retract`` calls. Calling the private
            # path avoids any future recursion concern if the public
            # wrapper grows additional pre/post-processing.
            return await self._do_message_retract(
                session_id=session_id, message_id=message_id,
            )

        if event.event_type == "external_inbound":
            active_run = self._run_store.get_active_run(session_id)
            if active_run is None:
                return False
            active_run.pending_events.append(event)
            return True

        if event.event_type == "child_run_completed":
            active_run = self._run_store.get_active_run(session_id)
            if active_run is None:
                logger.warning(
                    "child_run_completed for unknown session %s", session_id,
                )
                return False
            active_run.pending_events.append(event)
            return True

        if event.event_type in {
            "scheduled_fire",
            "sensor_event",
            "tool_advisory_arrival",
            "user_defer",
        }:
            active_run = self._run_store.get_active_run(session_id)
            if active_run is not None:
                active_run.pending_events.append(event)
                return True
            logger.info(
                "dispatch_event: no active run for %s event %s; skipping",
                event.event_type, event.event_id,
            )
            return False

        logger.warning("dispatch_event: unknown event_type %r", event.event_type)
        return False

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

    @staticmethod
    def _user_message_trigger(
        *,
        payload: UserMessagePayload,
        turn_id: str | None,
    ) -> RunTrigger:
        """Phase H+1: build a source-aware ``RunTrigger`` for a fresh run.

        - HTTP /chat & chat UI (``source`` in :data:`_MAGI_NATIVE_SOURCES`)
          → ``trigger_type="user_message"`` with ``source_channel="chat_sse"``
          (preserves the Phase H Task 6 behavior).
        - Any other source (``telegram``, ``weixin``, ``slack``, ...) →
          ``trigger_type="external_inbound"`` with ``source_channel`` set
          to the dispatcher source string so downstream consumers can
          reason about provenance.

        Used at the ``create_active_run`` call sites inside
        :meth:`handle_user_turn` / :meth:`ahandle_user_turn`.
        """
        if _is_external_source(payload.source):
            return RunTrigger(
                trigger_type="external_inbound",
                source_channel=payload.source.strip().lower(),
                requester=payload.user_id,
                priority="foreground",
                correlation=[turn_id] if turn_id else [],
                payload={"content": payload.content} if payload.content else {},
            )
        return RunTrigger(
            trigger_type="user_message",
            source_channel="chat_sse",
            requester=payload.user_id,
            priority="foreground",
            correlation=[turn_id] if turn_id else [],
            payload={"content": payload.content} if payload.content else {},
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
            active_run = self._run_store.create_active_run(
                payload.session_id,
                root_turn_id=turn_id,
                root_user_message=payload.content,
                trigger=self._user_message_trigger(payload=payload, turn_id=turn_id),
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
        # Phase H+1: external (telegram/weixin/...) inbounds landing on an
        # active run ALSO append a typed IncomingEvent. The legacy
        # ``pending_turns`` queue is kept for backward compat (session
        # turn queue already merges both queues since Phase H Task 4).
        if active_run is not None and _is_external_source(payload.source):
            active_run.pending_events.append(
                self._build_external_inbound_event(
                    payload=payload,
                    active_run_id=active_run.run_id,
                )
            )
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
                trigger=self._user_message_trigger(payload=payload, turn_id=turn_id),
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
        # Phase H+1: see ``handle_user_turn`` — mirror the IncomingEvent
        # emission on the async path so both routes behave identically.
        if active_run is not None and _is_external_source(payload.source):
            active_run.pending_events.append(
                self._build_external_inbound_event(
                    payload=payload,
                    active_run_id=active_run.run_id,
                )
            )
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
