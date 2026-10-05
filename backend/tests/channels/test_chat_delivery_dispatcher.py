"""Tests for channel-owned chat delivery dispatch."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.channels.chat_delivery_dispatcher import ChatDeliveryDispatcher
from magi.delivery.contracts import DeliveryFanoutResult
from magi_plugin_sdk.delivery import DeliveryReceipt


class _StubRouter:
    def __init__(self) -> None:
        self.retracted: list[DeliveryReceipt] = []
        self.deliveries: list[list] = []

    async def fanout_deliver(self, *, content, targets):
        self.deliveries.append(list(targets))
        return DeliveryFanoutResult(
            receipts=tuple(
                DeliveryReceipt(
                    channel_id=target.channel_type,
                    external_message_id=f"{target.channel_type}:1",
                    delivered_at_ms=100,
                    magi_session_id=target.magi_session_id,
                )
                for target in targets
            )
        )

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
@pytest.mark.parametrize(
    "store_enabled,has_receipts,session_id,run_id",
    [
        (True, True, "s1", "run-1"),
        (True, False, "s1", "run-1"),
        (False, True, "s1", "run-1"),
        (True, True, "", "run-1"),
        (True, True, "s1", ""),
    ],
)
async def test_retraction_only_forwards_persisted_receipts_with_complete_run_identity(
    store_enabled, has_receipts, session_id, run_id
):
    from unittest.mock import AsyncMock

    receipts = (
        [
            DeliveryReceipt(
                channel_id="telegram",
                external_message_id="tg:1",
                delivered_at_ms=101,
                magi_session_id="s1",
            )
        ]
        if has_receipts
        else []
    )
    router = SimpleNamespace(fanout_retract=AsyncMock())
    store = _StubReceiptsStore(receipts)
    dispatcher = ChatDeliveryDispatcher(
        delivery_router=router, receipts_store=store if store_enabled else None
    )
    await dispatcher.retract_run_deliveries(session_id=session_id, run_id=run_id)
    should_read = store_enabled and bool(session_id) and bool(run_id)
    assert store.list_calls == ([(session_id, run_id)] if should_read else [])
    if should_read and has_receipts:
        router.fanout_retract.assert_awaited_once_with(receipts=receipts)
    else:
        router.fanout_retract.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliver_final_response_excludes_failed_channel_types() -> None:
    router = _StubRouter()

    async def _prefs(_user_id: str) -> dict:
        return {"delivery_channels": ["chat_sse", "telegram"]}

    dispatcher = ChatDeliveryDispatcher(
        delivery_router=router,  # type: ignore[arg-type]
        user_prefs_provider=_prefs,
    )
    request = SimpleNamespace(
        context=SimpleNamespace(
            session_id="s1",
            session_run_id="run-1",
            user_id="u1",
            user_prefs={},
            active_run=None,
        )
    )

    result = await dispatcher.deliver_final_response(
        request,
        response_text="second segment",
        exclude_channel_types={"telegram"},
    )

    assert [target.channel_type for target in router.deliveries[0]] == [
        "chat_sse"
    ]
    assert [receipt.channel_id for receipt in result.receipts] == ["chat_sse"]
    assert result.failures == ()
