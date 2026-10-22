"""Exercise transport failures through the real durable chat outbox."""
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest
from magi_plugin_sdk.delivery import DeliveryReceipt

from magi.delivery.worker import DeliveryWorker
from tests.chat.test_outbound_delivery import seed


@pytest.mark.asyncio
@pytest.mark.parametrize("safe", [True, False])
async def test_uncertain_send_retries_only_with_same_provider_key(runtime_paths_with_schema, safe):
    store, _, _ = await seed(runtime_paths_with_schema)
    now = [200]
    calls = []

    async def send(target, content):
        calls.append((target, content.delivery_id))
        if len(calls) == 1:
            raise TimeoutError("Provider outcome unknown")
        return DeliveryReceipt(target.channel_type, "receipt-1", now[0], target.magi_session_id, content.delivery_id)

    sender = SimpleNamespace(supports_idempotent_delivery=safe, deliver=send)
    worker = DeliveryWorker(outbox=store, resolve=lambda _: sender, clock_ms=lambda: now[0])
    assert await worker.run_once()
    now[0] = 2000
    assert await worker.run_once() is safe
    result, = await store.list_outbound_deliveries(message_id="m1")
    if safe:
        assert len(calls) == 2 and calls[0] == calls[1]
        assert result.state == "succeeded"
    else:
        assert len(calls) == 1
        assert result.state == "uncertain"


@pytest.mark.asyncio
async def test_unavailable_channel_does_not_count_as_provider_attempt(runtime_paths_with_schema):
    store, _, _ = await seed(runtime_paths_with_schema)
    worker = DeliveryWorker(outbox=store, resolve=lambda _: None, clock_ms=lambda: 200)
    assert await worker.run_once()
    assert not await worker.run_once()
    item, = await store.list_outbound_deliveries(message_id="m1")
    assert item.attempt_count == 0 and item.state == "pending"


@pytest.mark.asyncio
async def test_wrong_receipt_keeps_uncertain_evidence(runtime_paths_with_schema):
    store, _, _ = await seed(runtime_paths_with_schema)
    sender = SimpleNamespace(supports_idempotent_delivery=False, deliver=AsyncMock(
        return_value=DeliveryReceipt("account:telegram", "receipt-1", 200, "another-session", "wrong-id"),
    ))
    worker = DeliveryWorker(outbox=store, resolve=lambda _: sender, clock_ms=lambda: 200)
    assert await worker.run_once()
    assert not await worker.run_once()
    item, = await store.list_outbound_deliveries(message_id="m1")
    assert item.state == "uncertain" and item.receipt is None
