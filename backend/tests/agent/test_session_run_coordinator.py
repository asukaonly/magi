from __future__ import annotations

import pytest

from magi.agent.runtime.contracts import FactRecord
from magi.agent.task_agents.common import IncomingFactKind
from magi.chat.task_agent.fact_classifier import ChatFactClassifier
from magi.chat.task_agent.session_run_coordinator import SessionRunCoordinator
from magi.control.cancel import SessionRunCancelToken
from magi.control.run_control import DetachSignal, null_run_control
from magi.events.events import EventTypes


def _user_fact(
    content: str,
    *,
    turn_id: str,
    run_disposition: str = "message",
) -> FactRecord:
    return FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "user_id": "u-chat",
            "session_id": "s-chat",
            "content": content,
            "turn_id": turn_id,
            "run_disposition": run_disposition,
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id=f"corr-{turn_id}",
    )


def _route_user(
    coordinator: SessionRunCoordinator,
    content: str,
    *,
    turn_id: str,
    run_disposition: str = "message",
):
    fact = _user_fact(
        content,
        turn_id=turn_id,
        run_disposition=run_disposition,
    )
    classified = ChatFactClassifier().classify(
        agent_id="u-chat",
        latest_fact=fact,
        batch_facts=[fact],
    )
    return coordinator.route(classified)


def test_first_turn_creates_root_run_without_auxiliary_router() -> None:
    coordinator = SessionRunCoordinator()

    routed = _route_user(
        coordinator,
        "Help me inspect the login flow.",
        turn_id="turn-1",
    )

    assert routed.active_run is not None
    assert routed.active_run.revision == 0
    assert routed.active_run.root_turn_id == "turn-1"
    assert routed.active_run.root_user_message == "Help me inspect the login flow."
    assert routed.planner_fact_kind == IncomingFactKind.USER_MESSAGE
    assert routed.run_disposition == "root"


def test_active_run_message_is_queued_with_one_uniform_disposition() -> None:
    coordinator = SessionRunCoordinator()
    _route_user(coordinator, "Inspect the login flow.", turn_id="turn-1")

    routed = _route_user(
        coordinator,
        "Also use the staging endpoint.",
        turn_id="turn-2",
    )

    assert routed.active_run is not None
    assert routed.planner_fact_kind == IncomingFactKind.OTHER_FACT
    assert routed.run_disposition == "message"
    assert [
        (item.turn_id, item.content, item.disposition)
        for item in routed.active_run.pending_turns
    ] == [("turn-2", "Also use the staging endpoint.", "message")]


def test_second_turn_starts_new_root_after_completion() -> None:
    coordinator = SessionRunCoordinator()
    first = _route_user(coordinator, "Inspect login.", turn_id="turn-1")
    assert first.active_run is not None
    assert coordinator.complete_run(
        session_id="s-chat",
        run_id=first.active_run.run_id,
        revision=first.active_run.revision,
    )

    second = _route_user(coordinator, "Inspect checkout.", turn_id="turn-2")

    assert second.active_run is not None
    assert second.active_run.root_turn_id == "turn-2"
    assert second.active_run.pending_turns == []
    assert second.run_disposition == "root"


def test_replace_turn_cancels_active_run_without_joining_its_input_queue() -> None:
    coordinator = SessionRunCoordinator()
    first = _route_user(coordinator, "Inspect login.", turn_id="turn-1")
    assert first.active_run is not None

    replacement = _route_user(
        coordinator,
        "Work on checkout instead.",
        turn_id="turn-2",
        run_disposition="replace",
    )

    assert replacement.run_disposition == "replace"
    assert replacement.active_run is not None
    assert replacement.active_run.status == "cancelling"
    assert replacement.active_run.cancel_reason == "user_replace"
    assert replacement.active_run.cancel_anchor_turn_id == "turn-1"
    assert [
        (item.turn_id, item.disposition)
        for item in replacement.active_run.pending_turns
    ] == [("turn-2", "replace")]

    completed, pending = coordinator.complete_run_with_pending_inputs(
        session_id="s-chat",
        run_id=replacement.active_run.run_id,
        revision=replacement.active_run.revision,
    )

    assert completed is True
    assert [(item.turn_id, item.disposition) for item in pending] == [
        ("turn-2", "replace")
    ]


@pytest.mark.asyncio
async def test_cancel_completion_returns_each_unconsumed_input_once() -> None:
    coordinator = SessionRunCoordinator()
    root = _route_user(coordinator, "Finish the root task.", turn_id="turn-1")
    assert root.active_run is not None
    _route_user(coordinator, "Handle this too.", turn_id="turn-2")
    control = null_run_control()
    control.cancel_token = SessionRunCancelToken(
        coordinator=coordinator,
        session_id="s-chat",
        run_id=root.active_run.run_id,
        revision=root.active_run.revision,
    )
    coordinator.register_active_run_control(
        "s-chat",
        root.active_run.run_id,
        control,
    )
    cancelling = coordinator.request_cancel(
        session_id="s-chat",
        requested_by="user",
        anchor_turn_id="turn-1",
    )
    assert cancelling is not None

    first_completed, first_inputs = coordinator.complete_run_with_pending_inputs(
        session_id="s-chat",
        run_id=cancelling.run_id,
        revision=cancelling.revision,
    )
    second_completed, second_inputs = coordinator.complete_run_with_pending_inputs(
        session_id="s-chat",
        run_id=cancelling.run_id,
        revision=cancelling.revision,
    )

    assert first_completed is True
    assert [item.turn_id for item in first_inputs] == ["turn-2"]
    assert second_completed is True
    assert second_inputs == []
    assert await control.cancel_token.is_cancelled()


def test_request_detach_flags_bound_signal() -> None:
    coordinator = SessionRunCoordinator()
    root = _route_user(coordinator, "Inspect login.", turn_id="turn-1")
    assert root.active_run is not None
    signal = DetachSignal()
    coordinator.bind_detach_signal("s-chat", signal)

    detached = coordinator.request_detach(
        session_id="s-chat",
        requested_by="user",
        reason="user_detach",
        note="continue in background",
    )

    assert detached is not None
    assert signal.is_requested() is True
    assert signal.payload is not None
    assert signal.payload.note == "continue in background"
