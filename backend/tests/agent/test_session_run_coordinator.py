from __future__ import annotations

from magi.agent.runtime.contracts import FactRecord
from magi.agent.task_agents.chat.fact_classifier import ChatFactClassifier
from magi.agent.task_agents.chat.interruption_classifier import InterruptionDisposition
from magi.agent.task_agents.chat.postprocess_service import CHAT_TOOL_LOOP_STEP_EVENT_TYPE
from magi.agent.task_agents.chat.session_run_coordinator import SessionRunCoordinator
from magi.agent.task_agents.common import IncomingFactKind
from magi.events.events import EventTypes


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
    coordinator = SessionRunCoordinator()
    first_fact = _user_fact("Inspect the login flow.", turn_id="turn-1")
    coordinator.route(
        classifier.classify(
            agent_id="u-chat",
            latest_fact=first_fact,
            batch_facts=[first_fact],
        )
    )
    augment_fact = _user_fact("Also, use the staging endpoint.", turn_id="turn-2")

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
        "Also, use the staging endpoint."
    ]


def test_interrupt_bumps_revision() -> None:
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


def test_augment_is_visible_at_next_checkpoint() -> None:
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
    augment_fact = _user_fact("Also, use the staging endpoint.", turn_id="turn-2")
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
            "Also, use the staging endpoint.",
        ]
    )
    assert [item.content for item in routed.checkpoint_pending_turns] == [
        "Also, use the staging endpoint."
    ]
