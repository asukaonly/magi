"""Lifecycle and checkpoint boundary tests for L0 attention."""

from __future__ import annotations

import asyncio
import time

import pytest

from magi.memory.l0.attention import (
    AttentionActionType,
    AttentionKind,
    AttentionUpdateAction,
)
from magi.memory.l0.working_memory import L0WorkingMemoryStore


def _store(tmp_path, **overrides) -> L0WorkingMemoryStore:
    return L0WorkingMemoryStore(
        checkpoint_db_path=str(tmp_path / "memory.db"),
        checkpoint_interval_seconds=overrides.pop(
            "checkpoint_interval_seconds",
            1,
        ),
        session_timeout_seconds=overrides.pop("session_timeout_seconds", 60),
        restore_on_restart=overrides.pop("restore_on_restart", True),
        max_concurrent_sessions=overrides.pop("max_concurrent_sessions", 64),
        **overrides,
    )


def _add(turn_id: str, summary: str) -> AttentionUpdateAction:
    return AttentionUpdateAction(
        action=AttentionActionType.ADD,
        kind=AttentionKind.FOCUS,
        summary=summary,
        source_turn_ids=(turn_id,),
        confidence=0.9,
        salience=0.8,
    )


@pytest.mark.asyncio
async def test_shutdown_flushes_dirty_attention_without_waiting_for_debounce(
    tmp_path,
) -> None:
    store = _store(tmp_path, checkpoint_interval_seconds=60)
    await store.apply_attention_actions(
        session_id="session-1",
        actions=[_add("turn-1", "正在完成 L0 改造")],
        expected_revision=0,
        last_processed_turn_id="turn-1",
    )

    await store.shutdown()

    restored = _store(tmp_path, checkpoint_interval_seconds=60)
    await restored.initialize()
    assert [
        item["summary"]
        for item in (await restored.get_workbench("session-1"))["attention_items"]
    ] == ["正在完成 L0 改造"]
    await restored.shutdown()


@pytest.mark.asyncio
async def test_scheduled_checkpoint_retries_after_transient_failure(
    tmp_path,
    monkeypatch,
) -> None:
    store = _store(tmp_path, checkpoint_interval_seconds=0)
    await store.initialize()
    real_checkpoint = store.checkpoint_session
    call_count = 0

    async def flaky_checkpoint(session_id):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient checkpoint failure")
        await real_checkpoint(session_id)

    monkeypatch.setattr(store, "checkpoint_session", flaky_checkpoint)
    await store.apply_attention_actions(
        session_id="session-1",
        actions=[_add("turn-1", "第一轮关注")],
        expected_revision=0,
        last_processed_turn_id="turn-1",
    )

    for _ in range(100):
        if call_count >= 2 and not store._checkpoint_tasks:
            break
        await asyncio.sleep(0.01)
    assert call_count >= 2
    await store.shutdown()

    restored = _store(tmp_path)
    await restored.initialize()
    assert [
        item["summary"]
        for item in (await restored.get_workbench("session-1"))["attention_items"]
    ] == ["第一轮关注"]
    await restored.shutdown()


@pytest.mark.asyncio
async def test_restore_keeps_old_session_with_unexpired_attention(tmp_path) -> None:
    store = _store(tmp_path, session_timeout_seconds=1)
    await store.apply_attention_actions(
        session_id="session-1",
        actions=[_add("turn-1", "仍需继续的关注")],
        expected_revision=0,
        last_processed_turn_id="turn-1",
    )
    store._sessions["session-1"]["last_active_at"] = time.time() - 30
    await store.checkpoint_all()
    await store.shutdown()

    restored = _store(tmp_path, session_timeout_seconds=1)
    await restored.initialize()

    assert (await restored.get_workbench("session-1"))["session"] is not None
    assert len(
        (await restored.get_workbench("session-1"))["attention_items"]
    ) == 1
    await restored.shutdown()


@pytest.mark.asyncio
async def test_restore_drops_old_session_after_attention_expiry(tmp_path) -> None:
    store = _store(tmp_path, session_timeout_seconds=1)
    await store.apply_attention_actions(
        session_id="session-1",
        actions=[_add("turn-1", "已经过期的关注")],
        expected_revision=0,
        last_processed_turn_id="turn-1",
    )
    item_id = next(iter(store._attention_items["session-1"]))
    store._attention_items["session-1"][item_id]["expires_at"] = time.time() - 1
    store._sessions["session-1"]["last_active_at"] = time.time() - 30
    await store.checkpoint_all()
    await store.shutdown()

    restored = _store(tmp_path, session_timeout_seconds=1)
    await restored.initialize()

    assert (await restored.get_workbench("session-1"))["session"] is None
    await restored.shutdown()


@pytest.mark.asyncio
async def test_capacity_evicts_lru_session_and_removes_checkpoint(tmp_path) -> None:
    store = _store(tmp_path, max_concurrent_sessions=2)
    for index in range(3):
        session_id = f"session-{index}"
        await store.apply_attention_actions(
            session_id=session_id,
            actions=[_add(f"turn-{index}", f"关注 {index}")],
            expected_revision=0,
            last_processed_turn_id=f"turn-{index}",
        )
        store._sessions[session_id]["last_active_at"] = float(index + 1)

    assert set(store._sessions) == {"session-1", "session-2"}
    await store.checkpoint_all()
    await store.shutdown()

    restored = _store(tmp_path, max_concurrent_sessions=2)
    await restored.initialize()
    snapshot = await restored.get_session_index_snapshot()
    assert set(snapshot["sessions"]) == {"session-1", "session-2"}
    await restored.shutdown()


@pytest.mark.asyncio
async def test_malformed_attention_row_is_discarded_without_losing_session(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    await store.apply_attention_actions(
        session_id="session-1",
        actions=[_add("turn-1", "有效关注")],
        expected_revision=0,
        last_processed_turn_id="turn-1",
    )
    await store.checkpoint_all()
    async with store._checkpoint_lock:
        from magi.core.sqlite import sqlite_connection_async

        async with sqlite_connection_async(store.checkpoint_db_path) as db:
            await db.execute(
                """
                INSERT INTO l0_attention_items(
                    item_id, session_id, kind, summary, status,
                    salience, confidence, evidence_mode,
                    source_turn_ids, source_event_ids,
                    first_seen_at, last_reinforced_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "malformed",
                    "session-1",
                    "focus",
                    "坏数据",
                    "active",
                    0.8,
                    0.9,
                    "direct",
                    "{bad",
                    "[]",
                    time.time(),
                    time.time(),
                    "{}",
                ),
            )
            await db.commit()

    restored = _store(tmp_path)
    await restored.initialize()
    assert [
        item["summary"]
        for item in (await restored.get_workbench("session-1"))["attention_items"]
    ] == ["有效关注"]
    await restored.shutdown()
    await store.shutdown()
