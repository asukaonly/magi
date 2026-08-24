from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.agent.execution.task_budget import (
    TaskBudgetExceeded,
    consume_task_llm_calls,
    prepay_task_llm_calls,
    reserve_task_worker_launches,
    task_execution_budget_scope,
)
from magi.chat import ChatStore
from magi.chat.task_agent.chat_task_agent import ChatTaskAgent
from magi.core.sqlite import sqlite_connection_async


@pytest.fixture
def chat_db_path(tmp_path: Path, ensure_db_schema) -> Path:
    db_path = tmp_path / "chat.db"
    ensure_db_schema("chat", db_path)
    return db_path


async def _create_root_turn(store: ChatStore, turn_id: str = "turn-root") -> None:
    await store.create_user_turn(
        session_id="session-budget",
        user_id="user-budget",
        turn_id=turn_id,
        message_text="Run one bounded task.",
        created_at_ms=100,
    )


@pytest.mark.asyncio
async def test_budget_survives_store_restart_and_preserves_original_limits(
    chat_db_path: Path,
) -> None:
    db_path = str(chat_db_path)
    store = ChatStore(db_path=db_path)
    await _create_root_turn(store)

    async with task_execution_budget_scope(
        root_turn_id="turn-root",
        store=store,
        max_llm_calls=2,
        max_worker_launches=1,
    ):
        await consume_task_llm_calls()
        await reserve_task_worker_launches()

    restarted = ChatStore(db_path=db_path)
    async with task_execution_budget_scope(
        root_turn_id="turn-root",
        store=restarted,
        max_llm_calls=99,
        max_worker_launches=99,
    ) as budget:
        assert budget.max_llm_calls == 2
        assert budget.llm_calls == 1
        assert budget.max_worker_launches == 1
        assert budget.worker_launches == 1
        await consume_task_llm_calls()
        with pytest.raises(TaskBudgetExceeded, match="llm_calls"):
            await consume_task_llm_calls()
        with pytest.raises(TaskBudgetExceeded, match="worker_launches"):
            await reserve_task_worker_launches()


@pytest.mark.asyncio
async def test_concurrent_admissions_cannot_oversell_durable_budget(
    chat_db_path: Path,
) -> None:
    store = ChatStore(db_path=str(chat_db_path))
    await _create_root_turn(store)

    async def reserve_once() -> bool:
        async with task_execution_budget_scope(
            root_turn_id="turn-root",
            store=store,
            max_llm_calls=3,
        ):
            try:
                await consume_task_llm_calls()
            except TaskBudgetExceeded:
                return False
            return True

    outcomes = await asyncio.gather(*(reserve_once() for _ in range(7)))

    assert outcomes.count(True) == 3
    assert outcomes.count(False) == 4
    state = await store.ensure_task_execution_budget(
        root_turn_id="turn-root",
        max_llm_calls=3,
        max_worker_launches=8,
    )
    assert state == (3, 3, 8, 0)


@pytest.mark.asyncio
async def test_concurrent_worker_admissions_cannot_oversell_durable_budget(
    chat_db_path: Path,
) -> None:
    store = ChatStore(db_path=str(chat_db_path))
    await _create_root_turn(store)

    async def reserve_once() -> bool:
        async with task_execution_budget_scope(
            root_turn_id="turn-root",
            store=store,
            max_worker_launches=3,
        ):
            try:
                await reserve_task_worker_launches()
            except TaskBudgetExceeded:
                return False
            return True

    outcomes = await asyncio.gather(*(reserve_once() for _ in range(9)))

    assert outcomes.count(True) == 3
    assert outcomes.count(False) == 6
    state = await store.ensure_task_execution_budget(
        root_turn_id="turn-root",
        max_llm_calls=30,
        max_worker_launches=3,
    )
    assert state == (30, 0, 3, 3)


@pytest.mark.asyncio
async def test_independent_store_instances_serialize_reserve_and_refund(
    chat_db_path: Path,
) -> None:
    first = ChatStore(db_path=str(chat_db_path))
    second = ChatStore(db_path=str(chat_db_path))
    await _create_root_turn(first)

    async def reserve_then_refund(store: ChatStore) -> None:
        async with task_execution_budget_scope(
            root_turn_id="turn-root",
            store=store,
            max_llm_calls=12,
        ):
            await prepay_task_llm_calls()

    await asyncio.gather(
        *(reserve_then_refund(first if index % 2 == 0 else second) for index in range(12))
    )

    state = await first.ensure_task_execution_budget(
        root_turn_id="turn-root",
        max_llm_calls=12,
        max_worker_launches=8,
    )
    assert state == (12, 0, 8, 0)


@pytest.mark.asyncio
async def test_unused_prepaid_capacity_is_released_durably(
    chat_db_path: Path,
) -> None:
    store = ChatStore(db_path=str(chat_db_path))
    await _create_root_turn(store)

    async with task_execution_budget_scope(
        root_turn_id="turn-root",
        store=store,
        max_llm_calls=2,
    ) as budget:
        await prepay_task_llm_calls()
        assert budget.llm_calls == 1

    reloaded = await store.ensure_task_execution_budget(
        root_turn_id="turn-root",
        max_llm_calls=2,
        max_worker_launches=8,
    )
    assert reloaded == (2, 0, 8, 0)


@pytest.mark.asyncio
async def test_chat_result_payload_rehydrates_budget_without_active_run(
    chat_db_path: Path,
) -> None:
    store = ChatStore(db_path=str(chat_db_path))
    await _create_root_turn(store)
    chat_agent = ChatTaskAgent.__new__(ChatTaskAgent)
    chat_agent._chat_store = store
    context = SimpleNamespace(
        active_run=None,
        latest_payload=SimpleNamespace(root_turn_id="turn-root"),
    )

    async with chat_agent.execution_scope(context):
        await consume_task_llm_calls()

    state = await store.ensure_task_execution_budget(
        root_turn_id="turn-root",
        max_llm_calls=30,
        max_worker_launches=8,
    )
    assert state == (30, 1, 8, 0)


@pytest.mark.asyncio
async def test_result_payload_root_wins_over_unrelated_active_run(
    chat_db_path: Path,
) -> None:
    store = ChatStore(db_path=str(chat_db_path))
    await _create_root_turn(store, turn_id="turn-result")
    await _create_root_turn(store, turn_id="turn-current")
    chat_agent = ChatTaskAgent.__new__(ChatTaskAgent)
    chat_agent._chat_store = store
    context = SimpleNamespace(
        active_run=SimpleNamespace(root_turn_id="turn-current"),
        latest_payload=SimpleNamespace(root_turn_id="turn-result"),
    )

    async with chat_agent.execution_scope(context):
        await consume_task_llm_calls()

    result_state = await store.ensure_task_execution_budget(
        root_turn_id="turn-result",
        max_llm_calls=30,
        max_worker_launches=8,
    )
    current_state = await store.ensure_task_execution_budget(
        root_turn_id="turn-current",
        max_llm_calls=30,
        max_worker_launches=8,
    )
    assert result_state == (30, 1, 8, 0)
    assert current_state == (30, 0, 8, 0)


@pytest.mark.asyncio
async def test_configured_chat_store_fails_closed_without_root_identity(
    chat_db_path: Path,
) -> None:
    chat_agent = ChatTaskAgent.__new__(ChatTaskAgent)
    chat_agent._chat_store = ChatStore(db_path=str(chat_db_path))
    context = SimpleNamespace(active_run=None, latest_payload=SimpleNamespace())

    with pytest.raises(RuntimeError, match="root identity is unavailable"):
        async with chat_agent.execution_scope(context):
            pass


@pytest.mark.asyncio
async def test_deleting_root_turn_cascades_execution_budget(
    chat_db_path: Path,
) -> None:
    store = ChatStore(db_path=str(chat_db_path))
    await _create_root_turn(store)
    await store.ensure_task_execution_budget(
        root_turn_id="turn-root",
        max_llm_calls=30,
        max_worker_launches=8,
    )

    async with sqlite_connection_async(store.db_path, profile="mixed") as db:
        await db.execute("DELETE FROM chat_turns WHERE turn_id = ?", ("turn-root",))
        await db.commit()
        cursor = await db.execute("SELECT COUNT(*) FROM chat_task_execution_budgets")
        row = await cursor.fetchone()

    assert row is not None
    assert int(row[0]) == 0


@pytest.mark.asyncio
async def test_deleting_root_while_prepaid_scope_unwinds_is_safe(
    chat_db_path: Path,
) -> None:
    store = ChatStore(db_path=str(chat_db_path))
    await _create_root_turn(store)

    async with task_execution_budget_scope(
        root_turn_id="turn-root",
        store=store,
    ):
        await prepay_task_llm_calls()
        async with sqlite_connection_async(store.db_path, profile="mixed") as db:
            await db.execute("DELETE FROM chat_turns WHERE turn_id = ?", ("turn-root",))
            await db.commit()


@pytest.mark.asyncio
async def test_budget_rejects_unknown_root_turn(chat_db_path: Path) -> None:
    store = ChatStore(db_path=str(chat_db_path))

    with pytest.raises(ValueError, match="root turn does not exist"):
        async with task_execution_budget_scope(
            root_turn_id="missing-turn",
            store=store,
        ):
            pass
