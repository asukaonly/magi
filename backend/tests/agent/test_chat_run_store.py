from __future__ import annotations

from magi.agent.task_agents.chat.run_contracts import RunResultDisposition
from magi.agent.task_agents.chat.run_store import SessionRunStore


def test_create_active_run_tracks_session_state() -> None:
    store = SessionRunStore()

    run = store.create_active_run(session_id="session-1", run_id="run-1")

    assert run.session_id == "session-1"
    assert run.run_id == "run-1"
    assert run.revision == 0
    assert run.pending_turns == []
    assert store.get_active_run("session-1") == run


def test_append_pending_turn_attaches_to_active_run() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")

    pending_turn = store.append_pending_turn(
        session_id="session-1",
        turn_id="turn-1",
        content="Please keep going after the interruption.",
    )

    active_run = store.get_active_run("session-1")

    assert pending_turn.turn_id == "turn-1"
    assert pending_turn.revision == 0
    assert active_run is not None
    assert active_run.pending_turns == [pending_turn]


def test_bump_revision_increments_active_run_revision() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")

    bumped_run = store.bump_revision("session-1")

    assert bumped_run.revision == 1
    assert store.get_active_run("session-1") == bumped_run


def test_mark_stale_result_tracks_stale_results_separately() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")
    store.bump_revision("session-1")

    stale_result = store.mark_stale_result(
        session_id="session-1",
        result_id="result-1",
        revision=0,
        payload={"content": "old result"},
    )

    active_run = store.get_active_run("session-1")

    assert stale_result.disposition == RunResultDisposition.STALE
    assert stale_result.revision == 0
    assert stale_result.payload == {"content": "old result"}
    assert active_run is not None
    assert active_run.accepted_results == []
    assert active_run.stale_results == [stale_result]
