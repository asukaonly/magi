"""Consumed-message repository contract tests."""
from __future__ import annotations

from _shared.db_schema import apply_chain_schema
import pytest

from magi.chat.storage.sqlite_store import SqliteChatRepository


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "chat.db")
    apply_chain_schema("chat", db_path)
    s = SqliteChatRepository(db_path=db_path)
    await s.initialize()
    return s


@pytest.mark.asyncio
async def test_record_then_find_returns_run_revision_tuple(store):
    await store.record_consumed(
        session_id="s1",
        run_id="r1",
        revision=0,
        message_ids=["m1", "m2", "m3"],
    )
    found = await store.find_runs_that_consumed(session_id="s1", message_id="m2")
    assert found == [("r1", 0)]
    await store.record_consumed(session_id="s1", run_id="r1", revision=0, message_ids=[])
    assert await store.find_runs_that_consumed(session_id="s1", message_id="m2") == found
    assert await store.find_runs_that_consumed(session_id="s1", message_id="nonexistent") == []
    assert await store.find_runs_that_consumed(session_id="missing", message_id="m2") == []


@pytest.mark.asyncio
async def test_find_returns_multiple_runs_for_same_message(store):
    await store.record_consumed(session_id="s1", run_id="r1", revision=0, message_ids=["m1"])
    await store.record_consumed(session_id="s1", run_id="r2", revision=0, message_ids=["m1"])
    await store.record_consumed(session_id="s1", run_id="r2", revision=1, message_ids=["m1"])
    found = await store.find_runs_that_consumed(session_id="s1", message_id="m1")
    assert found == [("r1", 0), ("r2", 0), ("r2", 1)]


@pytest.mark.asyncio
async def test_find_filters_by_session(store):
    await store.record_consumed(session_id="s1", run_id="r1", revision=0, message_ids=["m1"])
    await store.record_consumed(session_id="s2", run_id="r2", revision=0, message_ids=["m1"])
    found = await store.find_runs_that_consumed(session_id="s1", message_id="m1")
    assert found == [("r1", 0)]


@pytest.mark.asyncio
async def test_record_is_idempotent_on_duplicate(store):
    await store.record_consumed(session_id="s1", run_id="r1", revision=0, message_ids=["m1", "m1"])
    await store.record_consumed(session_id="s1", run_id="r1", revision=0, message_ids=["m1"])
    found = await store.find_runs_that_consumed(session_id="s1", message_id="m1")
    assert found == [("r1", 0)]


@pytest.mark.asyncio
async def test_clear_for_run_deletes_only_that_run(store):
    await store.record_consumed(session_id="s1", run_id="r1", revision=0, message_ids=["m1"])
    await store.record_consumed(session_id="s1", run_id="r2", revision=0, message_ids=["m1"])
    await store.clear_for_run(session_id="s1", run_id="r1")
    found = await store.find_runs_that_consumed(session_id="s1", message_id="m1")
    assert found == [("r2", 0)]
