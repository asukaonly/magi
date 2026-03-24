from __future__ import annotations

import pytest

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


def test_consume_pending_turns_only_clears_requested_revision() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")
    store.append_pending_turn(
        session_id="session-1",
        turn_id="turn-1",
        content="first revision augment",
    )
    store.bump_revision("session-1", clear_pending_turns=False)
    store.append_pending_turn(
        session_id="session-1",
        turn_id="turn-2",
        content="second revision augment",
    )

    consumed = store.consume_pending_turns("session-1", revision=1)
    active_run = store.get_active_run("session-1")

    assert [item.turn_id for item in consumed] == ["turn-2"]
    assert active_run is not None
    assert [item.turn_id for item in active_run.pending_turns] == ["turn-1"]


def test_mark_stale_result_tracks_stale_results_separately() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")
    store.bump_revision("session-1")

    stale_result = store.mark_stale_result(
        session_id="session-1",
        run_id="run-1",
        result_id="result-1",
        revision=0,
        payload={"content": "old result"},
    )

    active_run = store.get_active_run("session-1")

    assert stale_result.disposition == RunResultDisposition.STALE
    assert stale_result.run_id == "run-1"
    assert stale_result.revision == 0
    assert stale_result.payload == {"content": "old result"}
    assert active_run is not None
    assert active_run.accepted_results == []
    assert active_run.stale_results == [stale_result]


def test_record_result_routes_by_run_identity_and_revision() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")

    accepted_result = store.record_result(
        session_id="session-1",
        run_id="run-1",
        result_id="result-1",
        revision=0,
        payload={"content": "current"},
    )
    store.bump_revision("session-1")
    stale_result = store.record_result(
        session_id="session-1",
        run_id="run-1",
        result_id="result-2",
        revision=0,
        payload={"content": "older"},
    )

    active_run = store.get_active_run("session-1")

    assert accepted_result.disposition == RunResultDisposition.ACCEPTED
    assert accepted_result.run_id == "run-1"
    assert stale_result.disposition == RunResultDisposition.STALE
    assert stale_result.run_id == "run-1"
    assert active_run is not None
    assert [item.result_id for item in active_run.accepted_results] == ["result-1"]
    assert [item.result_id for item in active_run.stale_results] == ["result-2"]


def test_record_result_rejects_late_result_from_superseded_run() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")
    store.bump_revision("session-1")
    store.create_active_run(session_id="session-1", run_id="run-2")

    late_result = store.record_result(
        session_id="session-1",
        run_id="run-1",
        result_id="result-3",
        revision=0,
        payload={"content": "late"},
    )

    active_run = store.get_active_run("session-1")

    assert late_result.disposition == RunResultDisposition.STALE
    assert late_result.run_id == "run-1"
    assert active_run is not None
    assert active_run.run_id == "run-2"
    assert active_run.accepted_results == []
    assert [item.result_id for item in active_run.stale_results] == ["result-3"]


@pytest.mark.asyncio
async def test_session_run_store_restores_active_run_from_l0_checkpoint(tmp_path) -> None:
    from magi.memory.l0.working_memory import L0WorkingMemoryStore

    checkpoint_path = tmp_path / "l0_execution_state.db"
    l0_store = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        restore_on_restart=True,
    )
    await l0_store.initialize()

    store = SessionRunStore(l0_store=l0_store)
    store.create_active_run(session_id="session-1", run_id="run-1", root_turn_id="turn-1")
    store.append_pending_turn(
        session_id="session-1",
        turn_id="turn-2",
        content="补充一下，是 macOS",
    )
    store.record_result(
        session_id="session-1",
        run_id="run-1",
        result_id="result-1",
        revision=0,
        payload={"content": "current"},
    )
    await l0_store.checkpoint_session("session-1")

    restored_l0 = L0WorkingMemoryStore(
        checkpoint_db_path=str(checkpoint_path),
        restore_on_restart=True,
    )
    await restored_l0.initialize()
    restored_store = SessionRunStore(l0_store=restored_l0)

    active_run = restored_store.get_active_run("session-1")

    assert active_run is not None
    assert active_run.run_id == "run-1"
    assert active_run.root_turn_id == "turn-1"
    assert [item.turn_id for item in active_run.pending_turns] == ["turn-2"]
    assert [item.result_id for item in active_run.accepted_results] == ["result-1"]
