"""AgentRun typed trigger and pending-turn contracts."""
from __future__ import annotations

from magi.agent.task_agents.handlers.run_contracts import AgentRun
from magi_plugin_sdk.run_trigger import RunTrigger


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


def test_agent_run_accepts_pending_turns():
    from magi.agent.task_agents.handlers.run_contracts import PendingTurn
    legacy = PendingTurn(turn_id="t1", content="legacy", revision=0)
    run = AgentRun(
        session_id="s1",
        run_id="r1",
        pending_turns=[legacy],
    )
    assert run.pending_turns[0].content == "legacy"
