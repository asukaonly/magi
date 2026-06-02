"""Phase H Task 6: user-message-driven AgentRuns carry a typed RunTrigger.

When a new run is created in response to a user message (the fresh-turn
path inside ``SessionRunCoordinator.handle_user_turn`` /
``ahandle_user_turn``), the returned ``AgentRun`` should carry a
``RunTrigger(trigger_type="user_message", ...)`` describing where the
run came from.

These tests pin the contract at the smallest possible surface:
``SessionRunStore.create_active_run`` accepts a ``trigger=`` kwarg and
the returned + persisted-in-memory run reflects it.
"""
from __future__ import annotations

import pytest

from magi.chat.task_agent.run_store import SessionRunStore
from magi.agent.task_agents.common.contracts import UserMessagePayload
from magi_plugin_sdk.run_trigger import RunTrigger


def test_create_active_run_accepts_typed_trigger_and_returns_it() -> None:
    store = SessionRunStore()
    trigger = RunTrigger(
        trigger_type="user_message",
        source_channel="chat_sse",
        requester="u-1",
        priority="foreground",
        correlation=["turn-1"],
        payload={"content": "hello"},
    )

    run = store.create_active_run(
        session_id="s1",
        run_id="r1",
        root_turn_id="turn-1",
        root_user_message="hello",
        trigger=trigger,
    )

    assert run.trigger is not None
    assert run.trigger.trigger_type == "user_message"
    assert run.trigger.requester == "u-1"
    assert run.trigger.correlation == ["turn-1"]
    assert run.trigger.payload["content"] == "hello"


def test_get_active_run_preserves_trigger_after_create() -> None:
    """Trigger survives a get_active_run round-trip."""
    store = SessionRunStore()
    trigger = RunTrigger(
        trigger_type="user_message",
        source_channel="chat_sse",
        requester="u-1",
        priority="foreground",
        correlation=["turn-1"],
        payload={"content": "hi"},
    )
    store.create_active_run(
        session_id="s1",
        run_id="r1",
        root_turn_id="turn-1",
        root_user_message="hi",
        trigger=trigger,
    )

    fetched = store.get_active_run("s1")

    assert fetched is not None
    assert fetched.trigger is not None
    assert fetched.trigger.trigger_type == "user_message"
    assert fetched.trigger.requester == "u-1"


def test_create_active_run_without_trigger_stays_none() -> None:
    """Backward compat: callers that don't pass a trigger still work."""
    store = SessionRunStore()
    run = store.create_active_run(session_id="s1", run_id="r1")
    assert run.trigger is None


@pytest.mark.asyncio
async def test_handle_user_turn_fresh_run_carries_user_message_trigger() -> None:
    """End-to-end through SessionRunCoordinator.handle_user_turn: the
    fresh-run branch tags the new AgentRun with a user_message trigger
    derived from the UserMessagePayload."""
    from magi.chat.task_agent.session_run_coordinator import (
        SessionRunCoordinator,
    )

    coord = SessionRunCoordinator()
    payload = UserMessagePayload(
        user_id="u-7",
        session_id="s-fresh",
        content="say hi",
        turn_id="turn-fresh",
    )

    decision = coord.handle_user_turn(payload)

    assert decision.active_run is not None
    assert decision.active_run.trigger is not None
    assert decision.active_run.trigger.trigger_type == "user_message"
    assert decision.active_run.trigger.requester == "u-7"
    assert decision.active_run.trigger.correlation == ["turn-fresh"]
    assert decision.active_run.trigger.payload.get("content") == "say hi"
