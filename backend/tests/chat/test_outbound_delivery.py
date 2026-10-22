"""Real SQLite transactions exercise outbound recovery and clear fencing."""
import asyncio
from dataclasses import replace

import pytest
from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt
from magi_plugin_sdk.endpoints import EndpointRef

from magi.chat.store import ChatStore
from magi.chat.storage.outbound_delivery import insert_outbound_deliveries
from magi.core.sqlite import sqlite_connection_async
from magi.delivery.routing import DeliveryPlan


async def seed(paths, *, targets=1, commit=True, lifetime=100_000):
    store = ChatStore(db_path=str(paths.chat_db_path))
    plan = DeliveryPlan("s1", "u1", tuple(EndpointRef("account", "telegram", "group", str(n)) for n in range(targets)))
    content = DeliveryContent("hello", message_id="m1")
    async with sqlite_connection_async(store.db_path, profile="mixed") as db:
        await db.execute("INSERT INTO chat_sessions(session_id,user_id,title,created_at_ms,updated_at_ms) VALUES ('s1','u1','Chat',1,1)")
        await db.execute("""INSERT INTO chat_messages(message_id,session_id,user_id,role,message_kind,content_text,created_at_ms,sequence_no)
            VALUES ('m1','s1','u1','assistant','assistant_final','hello',1,1)""")
        await insert_outbound_deliveries(db, content=content, plan=plan, now_ms=100, lifetime_ms=lifetime)
        if commit:
            await db.commit()
        else:
            await db.rollback()
    return store, plan, content


@pytest.mark.asyncio
async def test_message_and_destinations_rollback_together(runtime_paths_with_schema):
    store, _, _ = await seed(runtime_paths_with_schema, commit=False)
    assert await store.list_outbound_deliveries(message_id="m1") == []
    async with sqlite_connection_async(store.db_path, profile="mixed") as db:
        assert await db.execute_fetchall("SELECT message_id FROM chat_messages") == []


@pytest.mark.asyncio
async def test_duplicate_intent_is_immutable_and_each_thread_is_independent(runtime_paths_with_schema):
    store, plan, content = await seed(runtime_paths_with_schema, targets=2)
    async with sqlite_connection_async(store.db_path, profile="mixed") as db:
        await insert_outbound_deliveries(db, content=content, plan=plan, now_ms=200)
        with pytest.raises(ValueError, match="different content"):
            await insert_outbound_deliveries(db, content=replace(content, text="changed"), plan=plan, now_ms=200)
    items = await store.list_outbound_deliveries(message_id="m1")
    assert len(items) == 2
    assert len({item.delivery_id for item in items}) == 2
    assert {item.endpoint.thread_id for item in items} == {"0", "1"}
    assert all(item.content.text == "hello" for item in items)


@pytest.mark.asyncio
async def test_only_one_worker_can_claim_and_expired_lease_cannot_settle(runtime_paths_with_schema):
    store, _, _ = await seed(runtime_paths_with_schema)
    claims = await asyncio.gather(*(store.claim_outbound_delivery(now_ms=200, lease_ms=100) for _ in range(2)))
    assert sum(item is not None for item in claims) == 1
    old = next(item for item in claims if item is not None)
    current = await store.claim_outbound_delivery(now_ms=301)
    assert current.delivery_id == old.delivery_id
    assert current.lease_token != old.lease_token
    assert not await store.begin_outbound_attempt(old, retry_safe=False, now_ms=302)
    assert await store.begin_outbound_attempt(current, retry_safe=False, now_ms=302)


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_safe", [True, False])
async def test_restart_after_provider_invocation_respects_idempotency(runtime_paths_with_schema, retry_safe):
    store, _, _ = await seed(runtime_paths_with_schema)
    item = await store.claim_outbound_delivery(now_ms=200, lease_ms=100)
    assert await store.begin_outbound_attempt(item, retry_safe=retry_safe, now_ms=201)
    restarted = ChatStore(db_path=store.db_path)
    next_item = await restarted.claim_outbound_delivery(now_ms=301)
    if retry_safe:
        assert next_item.delivery_id == item.delivery_id
        assert next_item.content == item.content
    else:
        assert next_item is None
        assert (await store.list_outbound_deliveries(message_id="m1"))[0].state == "uncertain"


@pytest.mark.asyncio
async def test_success_is_terminal_and_records_receipt(runtime_paths_with_schema):
    store, _, _ = await seed(runtime_paths_with_schema)
    item = await store.claim_outbound_delivery(now_ms=200)
    receipt = DeliveryReceipt("account:telegram", "group:7", 202, "s1")
    assert not await store.settle_outbound_delivery(item, state="succeeded", receipt=receipt, now_ms=201)
    assert await store.begin_outbound_attempt(item, retry_safe=False, now_ms=201)
    assert not await store.settle_outbound_delivery(item, state="pending", now_ms=202)
    assert await store.settle_outbound_delivery(item, state="succeeded", receipt=receipt, now_ms=202)
    assert await store.claim_outbound_delivery(now_ms=500) is None
    settled, = await store.list_outbound_deliveries(message_id="m1")
    assert settled.receipt == receipt
    assert settled.attempt_count == 1


@pytest.mark.asyncio
async def test_clear_barrier_blocks_attempt_and_late_receipt(runtime_paths_with_schema):
    store, _, _ = await seed(runtime_paths_with_schema)
    item = await store.claim_outbound_delivery(now_ms=200)
    async with sqlite_connection_async(store.db_path, profile="mixed") as db:
        await db.execute("INSERT INTO chat_cleared_session_scopes VALUES ('s1',201)")
        await db.commit()
    assert not await store.begin_outbound_attempt(item, retry_safe=False, now_ms=202)
    assert not await store.settle_outbound_delivery(item, state="failed", now_ms=202)
    assert await store.claim_outbound_delivery(now_ms=203) is None
    settled, = await store.list_outbound_deliveries(message_id="m1")
    assert settled.state == "cancelled"
    assert settled.content.text == ""


@pytest.mark.asyncio
async def test_expired_intent_and_deleted_message_cannot_deliver(runtime_paths_with_schema):
    store, _, _ = await seed(runtime_paths_with_schema, lifetime=10)
    assert await store.claim_outbound_delivery(now_ms=200) is None
    assert (await store.list_outbound_deliveries(message_id="m1"))[0].state == "expired"
    async with sqlite_connection_async(store.db_path, profile="mixed") as db:
        await db.execute("DELETE FROM chat_messages WHERE message_id='m1'")
        await db.commit()
    assert await store.list_outbound_deliveries(message_id="m1") == []
