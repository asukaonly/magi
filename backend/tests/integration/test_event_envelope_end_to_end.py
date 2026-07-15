"""End-to-end: envelope event_id / causation_id / trace_context flow into L1."""
from __future__ import annotations
import asyncio
import sqlite3
import tempfile
from pathlib import Path

import pytest

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import UserMessageReceived, TaskContext
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.events.tracing import start_span
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
async def test_envelope_event_id_lands_in_fact_events():
    bus, store, sub, tmp, base = await _setup()
    try:
        ctx = TaskContext(session_id="s", turn_id=None, task_id=None, user_id="u")
        e = Event(
            type=EventTypes.USER_MESSAGE_RECEIVED,
            data=UserMessageReceived(content="hi", context=ctx),
            source="chat",
        )
        envelope_id = e.event_id
        await bus.publish(e)
        await asyncio.sleep(0.05)
        await sub.drain()

        conn = sqlite3.connect(str(base / "l1_events.db"))
        try:
            row = conn.execute(
                "SELECT event_id FROM fact_events WHERE event_id = ?", (envelope_id,)
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == envelope_id
    finally:
        await _teardown(bus, store, sub, tmp)


@pytest.mark.asyncio
async def test_causation_chain_persisted():
    bus, store, sub, tmp, base = await _setup()
    try:
        ctx = TaskContext(session_id="s", turn_id=None, task_id=None, user_id="u")
        with start_span():
            a = Event(
                type=EventTypes.USER_MESSAGE_RECEIVED,
                data=UserMessageReceived(content="first", context=ctx),
                source="chat",
            )
            await bus.publish(a)

            b = Event(
                type=EventTypes.USER_MESSAGE_RECEIVED,
                data=UserMessageReceived(content="second", context=ctx),
                source="chat",
                causation_id=a.event_id,
            )
            await bus.publish(b)

        await asyncio.sleep(0.1)
        await sub.drain()

        conn = sqlite3.connect(str(base / "l1_events.db"))
        try:
            rows = conn.execute(
                "SELECT event_id FROM fact_events WHERE event_id IN (?, ?) ORDER BY content",
                (a.event_id, b.event_id),
            ).fetchall()
        finally:
            conn.close()

        # 19f637e0 slimmed fact_events to durable memory fields:
        # causation_id/trace_id are no longer persisted in L1 (execution
        # tracing is runtime_trace's domain). The durable contract left to
        # verify here is that both envelope event_ids landed in L1.
        assert {r[0] for r in rows} == {a.event_id, b.event_id}
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
