"""ChatRunConsumedEventsStore unit tests."""
from __future__ import annotations

import aiosqlite
import pytest

from magi.chat.conversation_log.store import ChatRunConsumedEventsStore


DDL = """
CREATE TABLE IF NOT EXISTS chat_run_consumed_events (
    session_id     TEXT    NOT NULL,
    run_id         TEXT    NOT NULL,
    revision       INTEGER NOT NULL DEFAULT 0,
    message_id     TEXT    NOT NULL,
    recorded_at_ms INTEGER NOT NULL,
    PRIMARY KEY (session_id, run_id, revision, message_id)
);
"""


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "chat.db")
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(DDL)
        await db.commit()
    s = ChatRunConsumedEventsStore(db_path=db_path)
    await s.initialize()
    return s


@pytest.mark.asyncio
async def test_record_then_find_returns_run_revision_tuple(store):
    await store.record_consumed(
        session_id="s1", run_id="r1", revision=0,
        message_ids=["m1", "m2", "m3"],
    )
    found = await store.find_runs_that_consumed(session_id="s1", message_id="m2")
    assert found == [("r1", 0)]


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


@pytest.mark.asyncio
async def test_record_empty_list_is_noop(store):
    await store.record_consumed(session_id="s1", run_id="r1", revision=0, message_ids=[])
    found = await store.find_runs_that_consumed(session_id="s1", message_id="m1")
    assert found == []


@pytest.mark.asyncio
async def test_find_no_match_returns_empty_list(store):
    found = await store.find_runs_that_consumed(session_id="s1", message_id="nonexistent")
    assert found == []
