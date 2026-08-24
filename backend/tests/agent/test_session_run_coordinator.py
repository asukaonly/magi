from __future__ import annotations

from collections import deque

import pytest

from magi.agent.runtime.contracts import FactRecord
from magi.chat.task_agent.fact_classifier import ChatFactClassifier
from magi.chat.task_agent.interruption_classifier import InterruptionDisposition
from magi.chat.task_agent.postprocess.constants import CHAT_TOOL_LOOP_STEP_EVENT_TYPE
from magi.chat.task_agent.session_run_coordinator import SessionRunCoordinator
from magi.control.run_control import DetachSignal
from magi.agent.task_agents.common import IncomingFactKind, UserMessagePayload
from magi.events.recall_feedback import RecallFeedbackKind, RecallFeedbackRequest
from magi.events.events import EventTypes


class _StubInterruptionClassifier:
    """Returns a scripted sequence of dispositions for sync ``classify`` calls.

    The production ``InterruptionClassifier.classify`` only returns
    ``INTERRUPT`` (via strict-phrase match) or ``DEFER`` — AUGMENT / STEER
    decisions require the async LLM-backed path. These tests want to
    exercise the *coordinator* routing logic for every disposition
    without dragging a real LLM into the loop, so they inject this stub
    to force the desired disposition.
    """

    def __init__(self, dispositions: list[InterruptionDisposition]) -> None:
        self._queue: deque[InterruptionDisposition] = deque(dispositions)
        self._last: InterruptionDisposition = InterruptionDisposition.DEFER

    def classify(self, context):  # type: ignore[no-untyped-def]
        _ = context
        if self._queue:
            self._last = self._queue.popleft()
        return self._last

    async def aclassify(self, context):  # type: ignore[no-untyped-def]
        return self.classify(context)

    def looks_like_strict_interrupt(self, user_text: str) -> bool:
        _ = user_text
        return False


def _user_fact(content: str, *, turn_id: str) -> FactRecord:
    return FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "u-chat",
            "session_id": "s-chat",
            "content": content,
            "turn_id": turn_id,
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id=f"corr-{turn_id}",
    )


def _checkpoint_fact(*, revision: int = 0) -> FactRecord:
    return FactRecord(
        agent_id="chat:u-chat",
        event_type=CHAT_TOOL_LOOP_STEP_EVENT_TYPE,
        payload={
            "user_id": "u-chat",
            "session_id": "s-chat",
            "stage": "tool_result",
            "response_preview": "checkpoint",
            "run_revision": revision,
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id=f"checkpoint-{revision}",
    )


def test_first_turn_creates_new_run() -> None:
    classifier = ChatFactClassifier()
    coordinator = SessionRunCoordinator()
    user_fact = _user_fact("Help me inspect the login flow.", turn_id="turn-1")

    classified = classifier.classify(
        agent_id="u-chat",
        latest_fact=user_fact,
        batch_facts=[user_fact],
    )

    routed = coordinator.route(classified)

    assert routed.active_run is not None
    assert routed.active_run.run_id
    assert routed.active_run.revision == 0
    assert routed.active_run.root_user_message == "Help me inspect the login flow."
    assert routed.planner_fact == user_fact
    assert routed.planner_fact_kind == IncomingFactKind.USER_MESSAGE
    assert routed.planner_user_message == "Help me inspect the login flow."


def test_interjection_during_active_run_is_classified_and_stored() -> None:
    classifier = ChatFactClassifier()
    coordinator = SessionRunCoordinator(
        interruption_classifier=_StubInterruptionClassifier([InterruptionDisposition.AUGMENT]),
    )
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=first_fact,
            batch_facts=[first_fact],
        )
    )
    augment_fact = _user_fact(
        "Instead of the login flow, inspect the signup flow.",
        turn_id="turn-2",
    )

    classified = classifier.classify(
        agent_id="u-chat",
        latest_fact=augment_fact,
        batch_facts=[augment_fact],
    )

    routed = coordinator.route(classified)

    assert routed.interruption_disposition == InterruptionDisposition.AUGMENT
    assert routed.planner_fact_kind == IncomingFactKind.OTHER_FACT
    assert routed.active_run is not None
    assert routed.active_run.revision == 0
    assert [item.content for item in routed.active_run.pending_turns] == [
        "Instead of the login flow, inspect the signup flow."
    ]
    assert routed.active_run.pending_turns[0].disposition == (InterruptionDisposition.AUGMENT.value)


def test_steer_interjection_is_queued_with_steer_disposition() -> None:
    classifier = ChatFactClassifier()
    coordinator = SessionRunCoordinator(
        interruption_classifier=_StubInterruptionClassifier([InterruptionDisposition.STEER]),
    )
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=first_fact,
            batch_facts=[first_fact],
        )
    )
    steer_fact = _user_fact("Also, use the staging endpoint.", turn_id="turn-2")

    routed = coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=steer_fact,
            batch_facts=[steer_fact],
        )
    )

    assert routed.interruption_disposition == InterruptionDisposition.STEER
    assert routed.active_run is not None
    assert [(item.content, item.disposition) for item in routed.active_run.pending_turns] == [
        ("Also, use the staging endpoint.", InterruptionDisposition.STEER.value)
    ]
    # STEER pending turns must not surface as a visible AUGMENT merge at the
    # next checkpoint — they are drained by the handler instead.
    assert coordinator.consume_checkpoint("s-chat").pending_turns == []
    # peek_steer_turns returns the queued turns without clearing them.
    assert [item.turn_id for item in coordinator.peek_steer_turns("s-chat")] == ["turn-2"]
    drained = coordinator.consume_steer_turns("s-chat")
    assert [item.turn_id for item in drained] == ["turn-2"]
    assert coordinator.peek_steer_turns("s-chat") == []


def test_second_turn_starts_fresh_run_after_previous_run_completes() -> None:
    classifier = ChatFactClassifier()
    coordinator = SessionRunCoordinator()
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    first_routed = coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=first_fact,
            batch_facts=[first_fact],
        )
    )
    assert first_routed.active_run is not None

    completed = coordinator.complete_run(
        session_id="s-chat",
        run_id=first_routed.active_run.run_id,
        revision=first_routed.active_run.revision,
    )

    second_fact = _user_fact("杭州啥天气", turn_id="turn-2")
    second_routed = coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=second_fact,
            batch_facts=[second_fact],
        )
    )

    assert completed is True
    assert second_routed.active_run is not None
    assert second_routed.run_disposition == "root"
    assert second_routed.planner_fact == second_fact
    assert second_routed.planner_fact_kind == IncomingFactKind.USER_MESSAGE
    assert second_routed.planner_user_message == "杭州啥天气"
    assert second_routed.active_run.root_turn_id == "turn-2"
    assert second_routed.active_run.pending_turns == []


def test_interrupt_bumps_revision() -> None:
    classifier = ChatFactClassifier()
    coordinator = SessionRunCoordinator(
        interruption_classifier=_StubInterruptionClassifier([InterruptionDisposition.INTERRUPT]),
    )
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=first_fact,
            batch_facts=[first_fact],
        )
    )
    interrupt_fact = _user_fact(
        "Stop and change the goal to debugging checkout.",
        turn_id="turn-2",
    )

    classified = classifier.classify(
        agent_id="u-chat",
        latest_fact=interrupt_fact,
        batch_facts=[interrupt_fact],
    )

    routed = coordinator.route(classified)

    assert routed.interruption_disposition == InterruptionDisposition.INTERRUPT
    assert routed.active_run is not None
    assert routed.active_run.revision == 1
    assert routed.active_run.root_user_message == "Stop and change the goal to debugging checkout."
    assert routed.planner_fact == interrupt_fact
    assert routed.planner_fact_kind == IncomingFactKind.USER_MESSAGE


def test_recall_feedback_interrupts_active_run_without_text_classification() -> None:
    interruption_classifier = _StubInterruptionClassifier([InterruptionDisposition.DEFER])
    coordinator = SessionRunCoordinator(
        interruption_classifier=interruption_classifier,
    )
    coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Inspect the login flow.",
            turn_id="turn-1",
        )
    )

    routed = coordinator.handle_user_turn(
        UserMessagePayload(
            user_id="u-chat",
            session_id="s-chat",
            content="Leave that record out.",
            turn_id="turn-2",
            recall_feedback=RecallFeedbackRequest(
                kind=RecallFeedbackKind.ITEM_IRRELEVANT,
                target_message_id="assistant-1",
                finding_ref="event:event-1",
            ),
        )
    )

    assert routed.interruption_disposition == InterruptionDisposition.INTERRUPT
    assert routed.active_run is not None
    assert routed.active_run.revision == 1
    assert routed.active_run.root_turn_id == "turn-2"
    assert len(interruption_classifier._queue) == 1


def test_augment_is_visible_at_next_checkpoint() -> None:
    classifier = ChatFactClassifier()
    coordinator = SessionRunCoordinator(
        interruption_classifier=_StubInterruptionClassifier([InterruptionDisposition.AUGMENT]),
    )
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=first_fact,
            batch_facts=[first_fact],
        )
    )
    augment_fact = _user_fact(
        "Instead of the login flow, inspect the signup flow.",
        turn_id="turn-2",
    )
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=augment_fact,
            batch_facts=[augment_fact],
        )
    )
    checkpoint_fact = _checkpoint_fact()

    classified = classifier.classify(
        agent_id="u-chat",
        latest_fact=checkpoint_fact,
        batch_facts=[checkpoint_fact],
    )

    routed = coordinator.route(classified)

    assert routed.planner_fact == checkpoint_fact
    assert routed.planner_fact_kind == IncomingFactKind.USER_MESSAGE
    assert routed.planner_user_message == "\n\n".join(
        [
            "Inspect the login flow.",
            "Instead of the login flow, inspect the signup flow.",
        ]
    )
    assert [item.content for item in routed.checkpoint_pending_turns] == [
        "Instead of the login flow, inspect the signup flow."
    ]


def test_request_cancel_marks_active_run_cancelling_and_complete_run_marks_cancelled() -> None:
    classifier = ChatFactClassifier()
    coordinator = SessionRunCoordinator()
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    routed = coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=first_fact,
            batch_facts=[first_fact],
        )
    )
    assert routed.active_run is not None

    cancelling_run = coordinator.request_cancel(
        session_id="s-chat",
        requested_by="user",
        reason="explicit_cancel",
        anchor_turn_id="turn-cancel",
    )

    assert cancelling_run is not None
    assert cancelling_run.status == "cancelling"
    assert cancelling_run.cancel_requested_by == "user"
    assert cancelling_run.cancel_reason == "explicit_cancel"
    assert cancelling_run.cancel_anchor_turn_id == "turn-cancel"

    completed = coordinator.complete_run(
        session_id="s-chat",
        run_id=cancelling_run.run_id,
        revision=cancelling_run.revision,
    )
    refreshed = coordinator.get_active_run("s-chat")

    assert completed is True
    assert refreshed is not None
    assert refreshed.status == "cancelled"


def test_cancelled_run_detaches_each_deferred_turn_only_once() -> None:
    coordinator = SessionRunCoordinator()
    coordinator._run_store.create_active_run(
        session_id="s-chat",
        run_id="run-cancel",
        root_turn_id="turn-root",
        root_user_message="Finish the root task",
    )
    coordinator._run_store.append_pending_turn(
        session_id="s-chat",
        turn_id="turn-deferred",
        content="Handle this after cancellation",
        disposition="defer",
    )
    active_run = coordinator.request_cancel(
        session_id="s-chat",
        requested_by="user",
    )
    assert active_run is not None

    first_completed, first_deferred = coordinator.complete_run_with_deferred(
        session_id="s-chat",
        run_id=active_run.run_id,
        revision=active_run.revision,
    )
    second_completed, second_deferred = coordinator.complete_run_with_deferred(
        session_id="s-chat",
        run_id=active_run.run_id,
        revision=active_run.revision,
    )

    assert first_completed is True
    assert [turn.turn_id for turn in first_deferred] == ["turn-deferred"]
    assert second_completed is True
    assert second_deferred == []
    refreshed = coordinator.get_active_run("s-chat")
    assert refreshed is not None
    assert refreshed.status == "cancelled"


def test_request_detach_flags_the_bound_signal_for_an_active_run() -> None:
    classifier = ChatFactClassifier()
    coordinator = SessionRunCoordinator()
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    routed = coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=first_fact,
            batch_facts=[first_fact],
        )
    )
    assert routed.active_run is not None

    signal = DetachSignal()
    coordinator.bind_detach_signal("s-chat", signal)

    detached_run = coordinator.request_detach(
        session_id="s-chat",
        requested_by="user",
        reason="user_detach",
        note="continue in background",
    )

    assert detached_run is not None
    assert detached_run.status == "running"
    assert signal.is_requested() is True
    assert signal.payload is not None
    assert signal.payload.requested_by == "user"
    assert signal.payload.reason == "user_detach"
    assert signal.payload.note == "continue in background"


@pytest.mark.asyncio
async def test_async_route_uses_model_interrupt_for_chinese_cancel_text() -> None:
    classifier = ChatFactClassifier()
    captured: dict[str, object] = {}

    class _AsyncInterruptClassifier:
        def classify(self, context):  # type: ignore[no-untyped-def]
            captured["sync_user_text"] = context.user_text
            return InterruptionDisposition.DEFER

        async def aclassify(self, context):  # type: ignore[no-untyped-def]
            captured["root_user_message"] = context.root_user_message
            captured["pending_turns"] = list(context.pending_turns)
            captured["user_text"] = context.user_text
            return InterruptionDisposition.INTERRUPT

    coordinator = SessionRunCoordinator(interruption_classifier=_AsyncInterruptClassifier())
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=first_fact,
            batch_facts=[first_fact],
        )
    )
    interrupt_fact = _user_fact("搞错了，不用做了", turn_id="turn-2")

    classified = classifier.classify(
        agent_id="u-chat",
        latest_fact=interrupt_fact,
        batch_facts=[interrupt_fact],
    )

    routed = await coordinator.aroute(classified)

    assert captured == {
        "root_user_message": "Inspect the login flow.",
        "pending_turns": [],
        "user_text": "搞错了，不用做了",
    }
    assert routed.interruption_disposition == InterruptionDisposition.INTERRUPT
    assert routed.active_run is not None
    assert routed.active_run.revision == 1
    assert routed.active_run.root_user_message == "搞错了，不用做了"


def test_steer_pending_turn_is_not_merged_as_augment_at_checkpoint() -> None:
    classifier = ChatFactClassifier()
    coordinator = SessionRunCoordinator()
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=first_fact,
            batch_facts=[first_fact],
        )
    )
    # Ordinary active-run input becomes a typed STEER for the main loop.
    steer_fact = _user_fact(
        "帮我看看 github 的仓库吧",
        turn_id="turn-2",
    )
    steer_routed = coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=steer_fact,
            batch_facts=[steer_fact],
        )
    )
    assert steer_routed.interruption_disposition == InterruptionDisposition.STEER

    checkpoint_fact = _checkpoint_fact()
    routed = coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=checkpoint_fact,
            batch_facts=[checkpoint_fact],
        )
    )

    # STEER turns must NOT merge through the legacy AUGMENT checkpoint; the planner
    # keeps processing the original root user message.
    assert routed.run_disposition != InterruptionDisposition.AUGMENT.value
    assert routed.checkpoint_pending_turns == []

    # The STEER turn remains in its dedicated queue for safe-boundary injection.
    active_run = coordinator.get_active_run("s-chat")
    assert active_run is not None
    assert [item.content for item in active_run.pending_turns] == [
        "帮我看看 github 的仓库吧",
    ]
    assert all(
        item.disposition == InterruptionDisposition.STEER.value for item in active_run.pending_turns
    )


def test_augment_is_merged_at_checkpoint_while_defer_stays_queued() -> None:
    classifier = ChatFactClassifier()
    coordinator = SessionRunCoordinator(
        interruption_classifier=_StubInterruptionClassifier(
            [InterruptionDisposition.AUGMENT, InterruptionDisposition.DEFER]
        ),
    )
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=_user_fact("Inspect the login flow.", turn_id="turn-1"),
            batch_facts=[_user_fact("Inspect the login flow.", turn_id="turn-1")],
        )
    )
    augment_fact = _user_fact(
        "Instead of the login flow, inspect the signup flow.",
        turn_id="turn-augment",
    )
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=augment_fact,
            batch_facts=[augment_fact],
        )
    )
    defer_fact = _user_fact(
        "帮我看看 github 的仓库吧",
        turn_id="turn-defer",
    )
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=defer_fact,
            batch_facts=[defer_fact],
        )
    )
    checkpoint_fact = _checkpoint_fact()

    routed = coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=checkpoint_fact,
            batch_facts=[checkpoint_fact],
        )
    )

    # Only AUGMENT merges into the visible planner message.
    assert routed.run_disposition == InterruptionDisposition.AUGMENT.value
    assert routed.planner_user_message == "\n\n".join(
        [
            "Inspect the login flow.",
            "Instead of the login flow, inspect the signup flow.",
        ]
    )
    assert [item.turn_id for item in routed.checkpoint_pending_turns] == ["turn-augment"]

    # DEFER stays attached until exact run completion.
    active_run = coordinator.get_active_run("s-chat")
    assert active_run is not None
    assert [item.turn_id for item in active_run.pending_turns] == ["turn-defer"]


def test_complete_run_atomically_detaches_deferred_pending_turns() -> None:
    classifier = ChatFactClassifier()
    coordinator = SessionRunCoordinator(
        interruption_classifier=_StubInterruptionClassifier(
            [InterruptionDisposition.AUGMENT, InterruptionDisposition.DEFER]
        ),
    )
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=_user_fact("Inspect the login flow.", turn_id="turn-1"),
            batch_facts=[_user_fact("Inspect the login flow.", turn_id="turn-1")],
        )
    )
    augment_fact = _user_fact("Also, use the staging endpoint.", turn_id="turn-augment")
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=augment_fact,
            batch_facts=[augment_fact],
        )
    )
    defer_fact = _user_fact(
        "帮我看看 github 的仓库吧",
        turn_id="turn-defer",
    )
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=defer_fact,
            batch_facts=[defer_fact],
        )
    )

    active_run = coordinator.get_active_run("s-chat")
    assert active_run is not None
    completed, deferred_turns = coordinator.complete_run_with_deferred(
        session_id="s-chat",
        run_id=active_run.run_id,
        revision=active_run.revision,
    )

    assert completed
    assert [item.turn_id for item in deferred_turns] == ["turn-defer"]
    assert all(
        item.disposition == InterruptionDisposition.DEFER.value
        for item in deferred_turns
    )
    assert coordinator.get_active_run("s-chat") is None
