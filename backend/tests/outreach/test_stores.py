import sqlite3

import pytest
from magi.outreach.contracts import OutreachIntentConflictError
from magi.outreach.stores import (
    OutreachDeliveryLogStore,
    OutreachOutboxStore,
)


async def _enqueue(
    store: OutreachOutboxStore,
    *,
    correlation_id: str = "c1",
    channel_scope: str = "telegram",
    intent_json: str = '{"k":1}',
    intent_fingerprint: str = "fingerprint-1",
):
    return await store.enqueue(
        correlation_id=correlation_id,
        channel_scope=channel_scope,
        intent_fingerprint=intent_fingerprint,
        intent_json=intent_json,
        release_at_ms=1000,
        created_at_ms=500,
    )


@pytest.mark.asyncio
async def test_outbox_enqueue_list_due_and_mark(runtime_paths_with_schema):
    store = OutreachOutboxStore(db_path=str(runtime_paths_with_schema.channels_db_path))
    enqueued = await _enqueue(store)
    rid = enqueued.row_id
    assert enqueued.created is True
    assert await store.list_due(now_ms=999) == []           # not yet due
    due = await store.list_due(now_ms=1000)                  # due
    assert len(due) == 1 and due[0]["id"] == rid
    await store.reschedule(rid, release_at_ms=1500)
    assert await store.list_due(now_ms=1499) == []
    assert len(await store.list_due(now_ms=1500)) == 1
    await store.mark_status(rid, "delivered")
    assert await store.list_due(now_ms=2000) == []           # no longer pending
    with sqlite3.connect(runtime_paths_with_schema.channels_db_path) as connection:
        assert connection.execute(
            "SELECT intent_json FROM outreach_outbox WHERE id = ?",
            (rid,),
        ).fetchone() == ("{}",)


@pytest.mark.asyncio
async def test_generic_status_update_cannot_reopen_outbox_row(
    runtime_paths_with_schema,
):
    store = OutreachOutboxStore(
        db_path=str(runtime_paths_with_schema.channels_db_path)
    )
    row_id = (await _enqueue(store)).row_id

    with pytest.raises(
        ValueError,
        match="status transition is not allowed",
    ):
        await store.mark_status(row_id, "pending")

    assert [row["id"] for row in await store.list_due(now_ms=1000)] == [row_id]


@pytest.mark.asyncio
async def test_attempting_outbox_row_is_not_replayed_after_restart(
    runtime_paths_with_schema,
):
    db_path = str(runtime_paths_with_schema.channels_db_path)
    first_store = OutreachOutboxStore(db_path=db_path)
    row_id = (await _enqueue(first_store)).row_id

    assert await first_store.begin_delivery_attempt(row_id) is True
    restarted_store = OutreachOutboxStore(db_path=db_path)

    assert await restarted_store.list_due(now_ms=2000) == []
    assert await restarted_store.begin_delivery_attempt(row_id) is False
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT status, intent_json FROM outreach_outbox WHERE id = ?",
            (row_id,),
        ).fetchone() == ("attempting", "{}")


@pytest.mark.asyncio
async def test_unattempted_outbox_delivery_can_return_to_pending(
    runtime_paths_with_schema,
):
    store = OutreachOutboxStore(
        db_path=str(runtime_paths_with_schema.channels_db_path)
    )
    row_id = (await _enqueue(store)).row_id

    assert await store.begin_delivery_attempt(row_id) is True
    assert await store.restore_pending_after_unattempted_delivery(
        row_id,
        intent_json='{"k":1}',
    ) is True
    due = await store.list_due(now_ms=1000)
    assert [row["id"] for row in due] == [row_id]
    assert due[0]["intent_json"] == '{"k":1}'


@pytest.mark.asyncio
async def test_delivery_log_dedup_and_budget(runtime_paths_with_schema):
    log = OutreachDeliveryLogStore(db_path=str(runtime_paths_with_schema.channels_db_path))
    assert await log.was_delivered("c1", "telegram") is False
    await log.record(correlation_id="c1", user_id="u1", channel_type="telegram", delivered_at_ms=1000)
    assert await log.was_delivered("c1", "telegram") is True
    assert await log.was_delivered("c1", "weixin") is False
    await log.record(correlation_id="c2", user_id="u1", channel_type="telegram", delivered_at_ms=1500)
    assert await log.count_for_user_since("u1", since_ms=900) == 2
    assert await log.count_for_user_since("u1", since_ms=1200) == 1


@pytest.mark.asyncio
async def test_outbox_reuses_same_logical_intent_after_restart(
    runtime_paths_with_schema,
):
    db_path = str(runtime_paths_with_schema.channels_db_path)
    first = OutreachOutboxStore(db_path=db_path)
    created = await _enqueue(first)
    await first.mark_status(created.row_id, "delivered")

    restarted = OutreachOutboxStore(db_path=db_path)
    reused = await _enqueue(restarted)

    assert reused.row_id == created.row_id
    assert reused.status == "delivered"
    assert reused.created is False


@pytest.mark.asyncio
async def test_outbox_rejects_changed_content_for_same_identity(
    runtime_paths_with_schema,
):
    store = OutreachOutboxStore(
        db_path=str(runtime_paths_with_schema.channels_db_path)
    )
    await _enqueue(store)

    with pytest.raises(
        OutreachIntentConflictError,
        match="reused with different content",
    ):
        await _enqueue(
            store,
            intent_json='{"k":2}',
            intent_fingerprint="fingerprint-2",
        )


@pytest.mark.asyncio
async def test_outbox_scopes_same_correlation_to_each_channel(
    runtime_paths_with_schema,
):
    store = OutreachOutboxStore(
        db_path=str(runtime_paths_with_schema.channels_db_path)
    )

    telegram = await _enqueue(store, channel_scope="telegram")
    weixin = await _enqueue(store, channel_scope="weixin")

    assert telegram.row_id != weixin.row_id
    assert telegram.created is True
    assert weixin.created is True
