"""Tests for channel-owned chat delivery dispatch."""

from __future__ import annotations

import pytest

from magi.channels.chat_delivery_dispatcher import ChatDeliveryDispatcher
from magi_plugin_sdk.delivery import DeliveryReceipt


class _StubRouter:
    def __init__(self) -> None:
        self.retracted: list[DeliveryReceipt] = []

    async def fanout_retract(self, *, receipts):
        self.retracted.extend(receipts)


class _StubReceiptsStore:
    def __init__(self, receipts) -> None:
        self._receipts = list(receipts)
        self.list_calls: list[tuple[str, str]] = []

    async def list_receipts(self, *, session_id, run_id, revision=None):
        self.list_calls.append((session_id, run_id))
        return list(self._receipts)


@pytest.mark.asyncio
async def test_retract_run_deliveries_reads_receipts_and_retracts_them() -> None:
    receipts = [
        DeliveryReceipt(
            channel_id="chat_sse",
            external_message_id=None,
            delivered_at_ms=100,
            magi_session_id="s1",
        ),
        DeliveryReceipt(
            channel_id="telegram",
            external_message_id="tg:1",
            delivered_at_ms=101,
            magi_session_id="s1",
        ),
    ]
    router = _StubRouter()
    store = _StubReceiptsStore(receipts)
    dispatcher = ChatDeliveryDispatcher(delivery_router=router, receipts_store=store)

    await dispatcher.retract_run_deliveries(session_id="s1", run_id="run-1")

    assert store.list_calls == [("s1", "run-1")]
    assert router.retracted == receipts


@pytest.mark.asyncio
async def test_retract_run_deliveries_noops_without_receipts_store() -> None:
    router = _StubRouter()
    dispatcher = ChatDeliveryDispatcher(delivery_router=router, receipts_store=None)

    await dispatcher.retract_run_deliveries(session_id="s1", run_id="run-1")

    assert router.retracted == []
