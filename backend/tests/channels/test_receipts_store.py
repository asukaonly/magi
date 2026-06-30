"""DeliveryReceiptsStore unit tests."""
from __future__ import annotations

import aiosqlite
import pytest

from magi.channels.receipts_store import DeliveryReceiptsStore
from magi_plugin_sdk.delivery import DeliveryReceipt


# Mirrors the delivery_receipts table in the channels v1 migration.
DELIVERY_RECEIPTS_DDL = """
CREATE TABLE IF NOT EXISTS delivery_receipts (
    receipt_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT    NOT NULL,
    run_id               TEXT    NOT NULL,
    revision             INTEGER NOT NULL DEFAULT 0,
    channel_id           TEXT    NOT NULL,
    external_message_id  TEXT,
    magi_session_id      TEXT    NOT NULL DEFAULT '',
    delivered_at_ms      INTEGER NOT NULL,
    created_at_ms        INTEGER NOT NULL
);
"""


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "channels.db")
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(DELIVERY_RECEIPTS_DDL)
        await db.commit()
    s = DeliveryReceiptsStore(db_path=db_path)
    await s.initialize()
    return s


@pytest.mark.asyncio
async def test_save_then_list_returns_inserted_receipts(store):
    receipts = [
        DeliveryReceipt(channel_id="chat_sse", external_message_id=None,
                        delivered_at_ms=100, magi_session_id="s1"),
        DeliveryReceipt(channel_id="telegram", external_message_id="tg:42",
                        delivered_at_ms=101, magi_session_id="s1"),
    ]
    await store.save_receipts(session_id="s1", run_id="r1", revision=0, receipts=receipts)
    listed = await store.list_receipts(session_id="s1", run_id="r1")
    assert len(listed) == 2
    by_channel = {r.channel_id: r for r in listed}
    assert by_channel["chat_sse"].external_message_id is None
    assert by_channel["telegram"].external_message_id == "tg:42"
    assert all(r.magi_session_id == "s1" for r in listed)


@pytest.mark.asyncio
async def test_list_filters_by_run_id(store):
    r_a = [DeliveryReceipt(channel_id="chat_sse", external_message_id=None,
                           delivered_at_ms=100, magi_session_id="s1")]
    r_b = [DeliveryReceipt(channel_id="telegram", external_message_id="tg:1",
                           delivered_at_ms=200, magi_session_id="s1")]
    await store.save_receipts(session_id="s1", run_id="r_a", revision=0, receipts=r_a)
    await store.save_receipts(session_id="s1", run_id="r_b", revision=0, receipts=r_b)
    listed_a = await store.list_receipts(session_id="s1", run_id="r_a")
    assert len(listed_a) == 1 and listed_a[0].channel_id == "chat_sse"
    listed_b = await store.list_receipts(session_id="s1", run_id="r_b")
    assert len(listed_b) == 1 and listed_b[0].channel_id == "telegram"


@pytest.mark.asyncio
async def test_list_filters_by_revision_when_supplied(store):
    r1 = [DeliveryReceipt(channel_id="chat_sse", external_message_id=None,
                          delivered_at_ms=100, magi_session_id="s1")]
    r2 = [DeliveryReceipt(channel_id="telegram", external_message_id="tg:1",
                          delivered_at_ms=200, magi_session_id="s1")]
    await store.save_receipts(session_id="s1", run_id="r1", revision=0, receipts=r1)
    await store.save_receipts(session_id="s1", run_id="r1", revision=1, receipts=r2)
    # Without filter → both revisions
    all_rev = await store.list_receipts(session_id="s1", run_id="r1")
    assert len(all_rev) == 2
    # With filter → only that revision
    only_rev_1 = await store.list_receipts(session_id="s1", run_id="r1", revision=1)
    assert len(only_rev_1) == 1
    assert only_rev_1[0].channel_id == "telegram"


@pytest.mark.asyncio
async def test_clear_receipts_removes_entries_for_run(store):
    receipts = [DeliveryReceipt(channel_id="chat_sse", external_message_id=None,
                                delivered_at_ms=100, magi_session_id="s1")]
    await store.save_receipts(session_id="s1", run_id="r1", revision=0, receipts=receipts)
    await store.clear_receipts(session_id="s1", run_id="r1")
    listed = await store.list_receipts(session_id="s1", run_id="r1")
    assert listed == []


@pytest.mark.asyncio
async def test_save_empty_list_is_noop(store):
    await store.save_receipts(session_id="s1", run_id="r1", revision=0, receipts=[])
    assert await store.list_receipts(session_id="s1", run_id="r1") == []
