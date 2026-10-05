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
async def test_save_preserves_receipt_order_and_empty_batches_do_not_erase_existing_revisions(
    store,
):
    receipts = [
        DeliveryReceipt(
            channel_id="chat_sse",
            external_message_id=None,
            delivered_at_ms=100,
            magi_session_id="s1",
        ),
        DeliveryReceipt(
            channel_id="telegram",
            external_message_id="tg:42",
            delivered_at_ms=101,
            magi_session_id="s1",
        ),
    ]
    await store.save_receipts(session_id="s1", run_id="r1", revision=0, receipts=receipts)
    for revision in (0, 1):
        await store.save_receipts(session_id="s1", run_id="r1", revision=revision, receipts=[])
    assert await store.list_receipts(session_id="s1", run_id="r1") == receipts
    assert await store.list_receipts(session_id="s1", run_id="r1", revision=0) == receipts
    assert await store.list_receipts(session_id="s1", run_id="r1", revision=1) == []


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
async def test_clear_removes_all_target_revisions_without_affecting_other_runs_or_sessions(store):
    records = {}
    for session_id, run_id, revision in [
        ("s1", "r1", 0),
        ("s1", "r1", 1),
        ("s1", "r2", 0),
        ("s2", "r1", 0),
    ]:
        receipt = DeliveryReceipt(
            channel_id="telegram",
            external_message_id=f"{session_id}:{run_id}:{revision}",
            delivered_at_ms=100 + revision,
            magi_session_id=session_id,
        )
        records[(session_id, run_id, revision)] = [receipt]
        await store.save_receipts(
            session_id=session_id, run_id=run_id, revision=revision, receipts=[receipt]
        )
    for _ in range(2):
        await store.clear_receipts(session_id="s1", run_id="r1")
        assert await store.list_receipts(session_id="s1", run_id="r1") == []
        for session_id, run_id in [("s1", "r2"), ("s2", "r1")]:
            assert (
                await store.list_receipts(session_id=session_id, run_id=run_id)
                == records[(session_id, run_id, 0)]
            )
