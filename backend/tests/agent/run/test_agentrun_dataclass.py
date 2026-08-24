"""Tests for the canonical AgentRun contract."""
from __future__ import annotations


def test_agentrun_class_exists() -> None:
    from magi.agent.task_agents.handlers.run_contracts import AgentRun

    assert AgentRun.__name__ == "AgentRun"
def test_agentrun_carries_live_session_state() -> None:
    from magi.agent.task_agents.handlers.run_contracts import AgentRun

    run = AgentRun(session_id="s1", run_id="r1")
    assert run.status == "running"
    assert run.revision == 0
    assert run.trigger is None


def test_agentrun_accepts_typed_trigger() -> None:
    from magi.agent.task_agents.handlers.run_contracts import AgentRun
    from magi_plugin_sdk.run_trigger import RunTrigger

    trigger = RunTrigger(
        trigger_type="user_message",
        source_channel=None,
        requester="u-1",
        priority="foreground",
    )
    run = AgentRun(
        session_id="s1",
        run_id="r1",
        trigger=trigger,
    )
    assert run.trigger is trigger
    assert run.trigger.trigger_type == "user_message"


def test_agentrun_pending_turns_unchanged() -> None:
    """Safe-boundary run inputs remain part of live run state."""
    from magi.agent.task_agents.handlers.run_contracts import AgentRun, PendingTurn

    run = AgentRun(session_id="s1", run_id="r1")
    run.pending_turns.append(PendingTurn(turn_id="t1", content="hi", revision=0))
    assert len(run.pending_turns) == 1
    assert run.pending_turns[0].turn_id == "t1"
