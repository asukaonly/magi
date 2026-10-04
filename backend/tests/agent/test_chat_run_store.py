from __future__ import annotations

import pytest

from magi.agent.task_agents.handlers.run_contracts import RunResultDisposition
from magi.chat.task_agent.run_store import SessionRunStore
from magi.control.run_control import null_run_control
from magi.memory.l0.attention import (
    AttentionActionType,
    AttentionKind,
    AttentionUpdateAction,
)
from magi.memory.l0.working_memory import L0WorkingMemoryStore


async def _seed_attention(
    workbench_store: L0WorkingMemoryStore,
) -> list[dict[str, object]]:
    updated = await workbench_store.apply_attention_actions(
        session_id="session-1",
        actions=[
            AttentionUpdateAction(
                action=AttentionActionType.ADD,
                kind=AttentionKind.FOCUS,
                summary="Keep discussing the login flow",
                source_turn_ids=("turn-context",),
            )
        ],
        expected_revision=0,
        last_processed_turn_id="turn-context",
    )
    assert updated is not None
    return updated["items"]


def test_request_cancel_marks_active_run_cancelling() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1", root_turn_id="turn-1")

    cancelling_run = store.request_cancel(
        "session-1",
        requested_by="local_user",
        reason="user_cancel",
        anchor_turn_id="turn-2",
    )

    assert cancelling_run.status == "cancelling"
    assert cancelling_run.cancel_requested_by == "local_user"
    assert cancelling_run.cancel_reason == "user_cancel"
    assert cancelling_run.cancel_anchor_turn_id == "turn-2"
    assert cancelling_run.cancel_requested_at is not None

    cancelled = store.mark_cancelled("session-1", run_id="run-1", revision=0)
    assert cancelled.status == "cancelled"
    assert cancelled.cancel_requested_by == "local_user"
    assert cancelled.cancel_reason == "user_cancel"
    assert cancelled.cancel_anchor_turn_id == "turn-2"
    assert cancelled.cancel_requested_at == cancelling_run.cancel_requested_at
    assert store.get_active_run("session-1") == cancelled


def test_complete_active_run_clears_session_state() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")
    store.register_active_run_control(
        "session-1",
        "run-1",
        null_run_control(),
    )
    store.append_pending_turn(
        session_id="session-1",
        turn_id="turn-2",
        content="follow-up message",
    )

    completed = store.complete_active_run(
        "session-1",
        run_id="run-1",
        revision=0,
    )

    assert completed is True
    assert store.get_active_run("session-1") is None
    assert store.get_active_run_control("session-1", "run-1") is None


def test_cancel_completion_unregisters_active_run_control() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")
    store.register_active_run_control(
        "session-1",
        "run-1",
        null_run_control(),
    )
    store.request_cancel("session-1", requested_by="local_user")

    completed = store.complete_active_run(
        "session-1",
        run_id="run-1",
        revision=0,
    )

    assert completed is True
    assert store.get_active_run_control("session-1", "run-1") is None


def test_replacing_session_root_discards_only_obsolete_controls() -> None:
    store = SessionRunStore()
    old_control = null_run_control()
    new_control = null_run_control()
    store.create_active_run(session_id="session-1", run_id="run-old")
    store.register_active_run_control("session-1", "run-old", old_control)

    store.create_active_run(session_id="session-1", run_id="run-new")
    store.register_active_run_control("session-1", "run-new", new_control)

    assert store.get_active_run_control("session-1", "run-old") is None
    assert (
        store.complete_active_run(
            "session-1",
            run_id="run-old",
            revision=0,
        )
        is False
    )
    assert store.get_active_run_control("session-1", "run-new") is new_control


def test_stale_revision_completion_does_not_clear_new_revision_control() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")
    store.register_active_run_control(
        "session-1",
        "run-1",
        null_run_control(),
    )

    store.bump_revision("session-1")
    new_control = null_run_control()
    store.register_active_run_control("session-1", "run-1", new_control)

    assert (
        store.complete_active_run(
            "session-1",
            run_id="run-1",
            revision=0,
        )
        is False
    )
    assert store.get_active_run_control("session-1", "run-1") is new_control


def test_complete_active_run_atomically_returns_current_unconsumed_inputs() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")
    pending = store.append_pending_turn(
        session_id="session-1",
        turn_id="turn-input",
        content="Handle this after the current task",
    )

    assert pending.turn_id == "turn-input"
    assert pending.revision == 0
    assert pending.content == "Handle this after the current task"
    assert store.get_active_run("session-1").pending_turns == [pending]

    completed, pending_inputs = store.complete_active_run_with_pending_inputs(
        "session-1",
        run_id="run-1",
        revision=0,
    )

    assert completed is True
    assert pending_inputs == [pending]
    assert store.get_active_run("session-1") is None


def test_complete_active_run_mismatch_does_not_detach_pending_inputs() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-current")
    store.append_pending_turn(
        session_id="session-1",
        turn_id="turn-input",
        content="Handle this after the current task",
    )

    completed, pending_inputs = store.complete_active_run_with_pending_inputs(
        "session-1",
        run_id="run-stale",
        revision=0,
    )

    active_run = store.get_active_run("session-1")
    assert completed is False
    assert pending_inputs == []
    assert active_run is not None
    assert [turn.turn_id for turn in active_run.pending_turns] == [
        "turn-input"
    ]


@pytest.mark.asyncio
async def test_run_lifecycle_preserves_existing_attention_at_each_transition(tmp_path):
    workbench_store = L0WorkingMemoryStore(
        checkpoint_db_path=str(tmp_path / "memory.db"), restore_on_restart=False
    )
    store = SessionRunStore(workbench_store=workbench_store)
    attention_before = await _seed_attention(workbench_store)
    run = store.create_active_run(
        session_id="session-1",
        run_id="run-1",
        root_turn_id="turn-1",
        root_user_message="Inspect the login flow",
    )
    assert (run.session_id, run.run_id, run.revision) == ("session-1", "run-1", 0)
    assert run.pending_turns == []
    assert store.get_active_run("session-1") == run
    assert (await workbench_store.get_workbench("session-1"))["attention_items"] == attention_before
    bumped = store.bump_revision("session-1")
    assert bumped.revision == 1
    store.set_root_turn(
        "session-1", turn_id="turn-2", content="Switch to the checkout issue instead"
    )
    current = store.get_active_run("session-1")
    assert current.root_turn_id == "turn-2"
    assert current.root_user_message == "Switch to the checkout issue instead"
    assert current.revision == 1
    assert (await workbench_store.get_workbench("session-1"))["attention_items"] == attention_before
    assert store.complete_active_run("session-1", run_id="run-1", revision=1) is True
    assert store.get_active_run("session-1") is None
    assert (await workbench_store.get_workbench("session-1"))["attention_items"] == attention_before


def test_consume_pending_turns_only_clears_requested_revision() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")
    store.append_pending_turn(
        session_id="session-1",
        turn_id="turn-1",
        content="first revision input",
    )
    store.bump_revision("session-1", clear_pending_turns=False)
    store.append_pending_turn(
        session_id="session-1",
        turn_id="turn-2",
        content="second revision input",
    )

    consumed = store.consume_pending_turns("session-1", revision=1)
    active_run = store.get_active_run("session-1")

    assert [item.turn_id for item in consumed] == ["turn-2"]
    assert active_run is not None
    assert [item.turn_id for item in active_run.pending_turns] == ["turn-1"]


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

    assert (accepted_result.result_id, accepted_result.revision, accepted_result.payload) == (
        "result-1",
        0,
        {"content": "current"},
    )
    assert (stale_result.result_id, stale_result.revision, stale_result.payload) == (
        "result-2",
        0,
        {"content": "older"},
    )
    assert active_run.accepted_results == [accepted_result]
    assert active_run.stale_results == [stale_result]


def test_record_result_after_cancel_is_forced_stale() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")
    store.request_cancel("session-1", requested_by="local_user", reason="user_cancel")

    stale_result = store.record_result(
        session_id="session-1",
        run_id="run-1",
        result_id="result-1",
        revision=0,
        payload={"content": "late but same revision"},
    )

    active_run = store.get_active_run("session-1")

    assert stale_result.disposition == RunResultDisposition.STALE
    assert active_run is not None
    assert active_run.accepted_results == []
    assert [item.result_id for item in active_run.stale_results] == ["result-1"]


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


def test_live_run_stores_own_independent_state_and_controls():
    first = SessionRunStore()
    second = SessionRunStore()
    first.create_active_run(session_id="session-1", run_id="run-1")
    control = null_run_control()
    first.register_active_run_control("session-1", "run-1", control)
    first.append_pending_turn(
        session_id="session-1", turn_id="first-input", content="first runtime input"
    )
    assert second.get_active_run("session-1") is None
    assert second.get_active_run_control("session-1", "run-1") is None
    second.create_active_run(session_id="session-1", run_id="run-2")
    assert second.complete_active_run("session-1", run_id="run-2", revision=0) is True
    active = first.get_active_run("session-1")
    assert active.run_id == "run-1"
    assert [turn.turn_id for turn in active.pending_turns] == ["first-input"]
    assert first.get_active_run_control("session-1", "run-1") is control


def test_running_revision_clears_previous_cancel_metadata() -> None:
    store = SessionRunStore()
    store.create_active_run(session_id="session-1", run_id="run-1")
    store.request_cancel(
        "session-1",
        requested_by="local_user",
        reason="user_cancel",
        anchor_turn_id="turn-2",
    )

    store.bump_revision("session-1")
    active_run = store.get_active_run("session-1")

    assert active_run is not None
    assert active_run.status == "running"
    assert active_run.cancel_requested_at is None
    assert active_run.cancel_requested_by is None
    assert active_run.cancel_reason is None
    assert active_run.cancel_anchor_turn_id is None
