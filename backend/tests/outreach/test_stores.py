import pytest
from magi.outreach.stores import OutreachOutboxStore, OutreachDeliveryLogStore


@pytest.mark.asyncio
async def test_outbox_enqueue_list_due_and_mark(runtime_paths_with_schema):
    store = OutreachOutboxStore(db_path=str(runtime_paths_with_schema.channels_db_path))
    rid = await store.enqueue(intent_json='{"k":1}', release_at_ms=1000, created_at_ms=500)
    assert isinstance(rid, int)
    assert await store.list_due(now_ms=999) == []           # not yet due
    due = await store.list_due(now_ms=1000)                  # due
    assert len(due) == 1 and due[0]["id"] == rid
    await store.mark_status(rid, "delivered")
    assert await store.list_due(now_ms=2000) == []           # no longer pending


@pytest.mark.asyncio
async def test_delivery_log_dedup_and_budget(runtime_paths_with_schema):
    log = OutreachDeliveryLogStore(db_path=str(runtime_paths_with_schema.channels_db_path))
    assert await log.was_delivered("c1") is False
    await log.record(correlation_id="c1", user_id="u1", channel_type="telegram", delivered_at_ms=1000)
    assert await log.was_delivered("c1") is True
    await log.record(correlation_id="c2", user_id="u1", channel_type="telegram", delivered_at_ms=1500)
    assert await log.count_for_user_since("u1", since_ms=900) == 2
    assert await log.count_for_user_since("u1", since_ms=1200) == 1
