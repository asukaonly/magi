"""Tests for the canonical AgentRun contract."""
from __future__ import annotations


def test_agentrun_class_exists() -> None:
    from magi.agent.task_agents.handlers.run_contracts import AgentRun

    assert AgentRun.__name__ == "AgentRun"
def test_agentrun_carries_phase_e_fields_with_defaults() -> None:
    """New Phase E fields default-factory so existing constructors don't break."""
    from magi.agent.task_agents.handlers.run_contracts import AgentRun

    run = AgentRun(session_id="s1", run_id="r1")
    # Existing fields
    assert run.status == "running"
    assert run.revision == 0
    # New Phase E fields
    assert run.graph == ()
    assert run.node_states == {}
    assert run.consumed_events == ()
    assert run.trigger is None
    assert run.deliveries == ()


def test_agentrun_accepts_phase_e_fields_on_construction() -> None:
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
        graph=("tool_loop", "validate"),
        node_states={"tool_loop": {"iterations": 2}},
        consumed_events=("e1", "e2"),
        trigger=trigger,
        deliveries=("chat_sse",),
    )
    assert run.graph == ("tool_loop", "validate")
    assert run.node_states == {"tool_loop": {"iterations": 2}}
    assert run.consumed_events == ("e1", "e2")
    assert run.trigger is trigger
    assert run.trigger.trigger_type == "user_message"
    assert run.deliveries == ("chat_sse",)


def test_agentrun_pending_turns_unchanged() -> None:
    """Phase A/B pending_turns mechanism preserved exactly."""
    from magi.agent.task_agents.handlers.run_contracts import AgentRun, PendingTurn

    run = AgentRun(session_id="s1", run_id="r1")
    run.pending_turns.append(PendingTurn(turn_id="t1", content="hi", revision=0))
    assert len(run.pending_turns) == 1
    assert run.pending_turns[0].turn_id == "t1"
