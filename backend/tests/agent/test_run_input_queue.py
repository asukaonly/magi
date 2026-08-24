from __future__ import annotations

import pytest

from magi.chat.task_agent.run_input_queue import RunInputQueue
from magi.chat.task_agent.run_store import SessionRunStore


@pytest.mark.asyncio
async def test_drain_injects_current_revision_inputs_once() -> None:
    store = SessionRunStore()
    run = store.create_active_run(
        "session-1",
        run_id="run-1",
        root_turn_id="turn-root",
    )
    store.append_pending_turn("session-1", "turn-2", "Use Python 3.10")
    consumed = []

    async def _record(items):  # type: ignore[no-untyped-def]
        consumed.extend(items)

    queue = RunInputQueue(
        run_store=store,
        session_id="session-1",
        run_id=run.run_id,
        revision=run.revision,
        root_turn_id=run.root_turn_id,
        on_consumed=_record,
    )

    first = await queue.drain()
    second = await queue.drain()

    assert [item.content for item in first] == ["Use Python 3.10"]
    assert first[0].metadata == {
        "turn_id": "turn-2",
        "run_id": "run-1",
        "revision": 0,
    }
    assert second == []
    assert [(item.turn_id, item.anchor_turn_id, item.reason) for item in consumed] == [
        ("turn-2", "turn-root", "message")
    ]


@pytest.mark.asyncio
async def test_drain_does_not_consume_mismatched_run_revision() -> None:
    store = SessionRunStore()
    store.create_active_run(
        "session-1",
        run_id="run-1",
        root_turn_id="turn-root",
    )
    store.append_pending_turn("session-1", "turn-2", "Follow up")
    queue = RunInputQueue(
        run_store=store,
        session_id="session-1",
        run_id="run-stale",
        revision=0,
        root_turn_id="turn-root",
    )

    assert await queue.drain() == []
    active = store.get_active_run("session-1")
    assert active is not None
    assert [item.turn_id for item in active.pending_turns] == ["turn-2"]


@pytest.mark.asyncio
async def test_projection_failure_restores_unconsumed_input() -> None:
    store = SessionRunStore()
    run = store.create_active_run(
        "session-1",
        run_id="run-1",
        root_turn_id="turn-root",
    )
    store.append_pending_turn("session-1", "turn-2", "Follow up")

    async def _fail(_items):  # type: ignore[no-untyped-def]
        raise RuntimeError("projection unavailable")

    queue = RunInputQueue(
        run_store=store,
        session_id="session-1",
        run_id=run.run_id,
        revision=run.revision,
        root_turn_id=run.root_turn_id,
        on_consumed=_fail,
    )

    with pytest.raises(RuntimeError, match="projection unavailable"):
        await queue.drain()

    active = store.get_active_run("session-1")
    assert active is not None
    assert [item.turn_id for item in active.pending_turns] == ["turn-2"]
