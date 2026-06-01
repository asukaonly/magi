"""Phase H Task 4: turn queue consumes new pending_events alongside legacy pending_turns."""
from __future__ import annotations

from magi.agent.task_agents.chat.run_contracts import AgentRun, PendingTurn
from magi.agent.task_agents.chat.session_turn_queue import (
    SessionRunTurnQueueMixin,
)
from magi_plugin_sdk.run_trigger import IncomingEvent


def _current_revision_pending_turns(active_run):
    """Test shim — invokes the mixin's static helper."""
    return SessionRunTurnQueueMixin._current_revision_pending_turns(active_run)


def test_current_revision_yields_legacy_pending_turns():
    legacy = PendingTurn(turn_id="t1", content="legacy", revision=0)
    run = AgentRun(session_id="s1", run_id="r1", pending_turns=[legacy])
    out = _current_revision_pending_turns(run)
    assert any(t.content == "legacy" for t in out)


def test_current_revision_yields_pending_events_of_steer_type():
    steer = IncomingEvent(
        event_id="e1",
        event_type="user_steer",
        target_run_id="r1",
        arrived_at_ms=100,
        payload={"content": "wait actually...", "revision": 0},
    )
    run = AgentRun(session_id="s1", run_id="r1", pending_events=[steer])
    out = _current_revision_pending_turns(run)
    # The IncomingEvent appears as a PendingTurn-shaped item with the
    # same content
    contents = [t.content for t in out]
    assert "wait actually..." in contents


def test_current_revision_yields_both_sources_combined():
    legacy = PendingTurn(turn_id="t1", content="legacy", revision=0)
    new_event = IncomingEvent(
        event_id="e2",
        event_type="user_steer",
        target_run_id="r1",
        arrived_at_ms=200,
        payload={"content": "new", "revision": 0},
    )
    run = AgentRun(
        session_id="s1",
        run_id="r1",
        pending_turns=[legacy],
        pending_events=[new_event],
    )
    out = _current_revision_pending_turns(run)
    contents = [t.content for t in out]
    assert "legacy" in contents
    assert "new" in contents


def test_current_revision_skips_non_steer_events():
    """Only user_steer / user_augment IncomingEvents become turn-queue items;
    user_retract, child_run_completed, etc. are handled by the dispatcher."""
    retract = IncomingEvent(
        event_id="e1",
        event_type="user_retract",
        target_run_id="r1",
        arrived_at_ms=100,
        payload={"message_id": "m1"},
    )
    run = AgentRun(session_id="s1", run_id="r1", pending_events=[retract])
    out = _current_revision_pending_turns(run)
    # The retract event should NOT appear as a pending turn
    assert out == []
