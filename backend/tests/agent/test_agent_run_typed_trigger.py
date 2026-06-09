"""Phase H Task 3: AgentRun.trigger is typed; pending_events is new."""
from __future__ import annotations

from magi.agent.task_agents.handlers.run_contracts import AgentRun
from magi_plugin_sdk.run_trigger import RunTrigger, IncomingEvent


def test_agent_run_accepts_typed_trigger():
    trigger = RunTrigger(
        trigger_type="user_message",
        source_channel=None,
        requester="u-1",
        priority="foreground",
        correlation=["fact-1"],
        payload={"content": "hi"},
    )
    run = AgentRun(
        session_id="s1",
        run_id="r1",
        trigger=trigger,
    )
    assert run.trigger is trigger
    assert run.trigger.trigger_type == "user_message"


def test_agent_run_trigger_defaults_to_none():
    """Backward compat — callers that don't set trigger still construct."""
    run = AgentRun(session_id="s1", run_id="r1")
    assert run.trigger is None


def test_agent_run_pending_events_defaults_to_empty_list():
    run = AgentRun(session_id="s1", run_id="r1")
    assert run.pending_events == []


def test_agent_run_pending_events_accepts_incoming_event():
    event = IncomingEvent(
        event_id="e1",
        event_type="user_steer",
        target_run_id="r1",
        arrived_at_ms=100,
        payload={"content": "wait"},
    )
    run = AgentRun(
        session_id="s1",
        run_id="r1",
        pending_events=[event],
    )
    assert run.pending_events[0].event_id == "e1"


def test_agent_run_pending_turns_still_works_for_backward_compat():
    """Phase H keeps pending_turns alongside pending_events for now."""
    from magi.agent.task_agents.handlers.run_contracts import PendingTurn
    legacy = PendingTurn(turn_id="t1", content="legacy", revision=0)
    run = AgentRun(
        session_id="s1",
        run_id="r1",
        pending_turns=[legacy],
    )
    assert run.pending_turns[0].content == "legacy"
