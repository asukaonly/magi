"""Verify durable envelope identity and content through memory ingestion."""
from __future__ import annotations
import asyncio
import sqlite3
import tempfile
from pathlib import Path

import pytest

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import UserMessageReceived, TaskContext
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.memory import UnifiedMemoryStore
from magi.memory.subscribers.memory_ingestion_subscriber import MemoryIngestionSubscriber


async def _setup():
    bus = InMemoryMessageBusBackend()
    await bus.start()
    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    store = UnifiedMemoryStore(
        l1_db_path=str(base / "l1_events.db"),
        memory_db_path=str(base / "memory.db"),
        persist_dir=str(base / "memories"),
        l2_batch_flush_interval_seconds=0,
    )
    await store.initialize()
    bus.bind_memory_operation_epoch(store.memory_operation_epoch)
    sub = MemoryIngestionSubscriber(event_bus=bus, unified_memory=store)
    await sub.start()
    return bus, store, sub, tmp, base


async def _teardown(bus, store, sub, tmp):
    await sub.stop()
    await store.shutdown()
    await bus.stop()
    tmp.cleanup()


@pytest.mark.asyncio
async def test_envelope_ids_and_content_survive_multiple_publications():
    bus, store, sub, tmp, base = await _setup()
    try:
        context = TaskContext(session_id="s", turn_id=None, task_id=None, user_id="u")
        first = Event(
            type=EventTypes.USER_MESSAGE_RECEIVED,
            data=UserMessageReceived(content="first", context=context),
            source="chat",
        )
        second = Event(
            type=EventTypes.USER_MESSAGE_RECEIVED,
            data=UserMessageReceived(content="second", context=context),
            source="chat",
            causation_id=first.event_id,
        )
        for event in [first, second]:
            await bus.publish(event)
        await asyncio.sleep(0.05)
        await sub.drain()
        with sqlite3.connect(str(base / "l1_events.db")) as connection:
            rows = connection.execute("SELECT event_id,content FROM fact_events").fetchall()
        assert set(rows) == {(first.event_id, "first"), (second.event_id, "second")}
    finally:
        await _teardown(bus, store, sub, tmp)


@pytest.mark.asyncio
async def test_fanout_does_not_duplicate_event_id():
    """Publishing the same Event twice must yield a single fact_events row
    (idempotency via INSERT OR IGNORE on UNIQUE event_id)."""
    bus, store, sub, tmp, base = await _setup()
    try:
        ctx = TaskContext(session_id="s", turn_id=None, task_id=None, user_id="u")
        e = Event(
            type=EventTypes.USER_MESSAGE_RECEIVED,
            data=UserMessageReceived(content="once", context=ctx),
            source="chat",
        )
        await bus.publish(e)
        await bus.publish(e)
        await asyncio.sleep(0.1)
        await sub.drain()

        conn = sqlite3.connect(str(base / "l1_events.db"))
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM fact_events WHERE event_id = ?",
                (e.event_id,),
            ).fetchone()[0]
        finally:
            conn.close()

        assert count == 1
    finally:
        await _teardown(bus, store, sub, tmp)
