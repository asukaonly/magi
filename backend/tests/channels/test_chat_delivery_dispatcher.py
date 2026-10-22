"""Tests for channel-owned chat delivery dispatch."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.channels.chat_delivery_dispatcher import ChatDeliveryDispatcher
from magi.delivery.contracts import DeliveryFanoutResult
from magi_plugin_sdk.delivery import DeliveryReceipt
from magi_plugin_sdk.endpoints import EndpointRef, IngressContext


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
        return {"delivery_targets": [{"connection_id": None, "contribution_id": "telegram", "target_id": "chat-1"}]}

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


@pytest.mark.asyncio
async def test_reply_uses_recorded_connection_and_thread() -> None:
    router = _StubRouter()
    endpoint = EndpointRef("account-2", "telegram", "group-1", "topic-3")
    request = SimpleNamespace(context=SimpleNamespace(
        session_id="s1", session_run_id="", user_id="u1", user_prefs={},
        active_run=SimpleNamespace(trigger=SimpleNamespace(
            ingress=IngressContext("message", "event-1", endpoint, endpoint),
        )),
    ))
    plan = await ChatDeliveryDispatcher(delivery_router=router).resolve_delivery_plan(request.context)
    target, = [target for target in plan.channel_targets() if target.channel_type != "chat_sse"]
    assert (target.channel_type, target.external_chat_id, target.external_thread_id) == (
        "account-2:telegram", "group-1", "topic-3",
    )


@pytest.mark.parametrize("selected", [[], [EndpointRef("requested", "telegram", "target").to_dict()]])
async def test_run_selection_overrides_preferences_but_retains_origin(selected):
    from magi.agent.task_agents.common.contracts import UserMessagePayload
    from magi.agent.run_triggers import build_user_message_trigger
    from magi_plugin_sdk.run_trigger import RunTrigger
    origin = EndpointRef("phone", "telegram", "owner")
    payload = UserMessagePayload.from_dict({
        "user_id": "u1", "session_id": "s1", "content": "request",
        "metadata": {"delivery_targets": selected},
    }, fallback_user_id="u1")
    payload = UserMessagePayload.from_dict(payload.to_dict(), fallback_user_id="u1")
    trigger = build_user_message_trigger(source="api", requester="u1", content="request", turn_id="turn",
        ingress=IngressContext("message", "turn", origin, origin), delivery_targets=payload.delivery_targets)
    context = SimpleNamespace(
        session_id="s1", user_id="u1", user_prefs={"delivery_targets": [EndpointRef("default", "telegram", "unused").to_dict()]},
        active_run=SimpleNamespace(trigger=RunTrigger.from_dict(trigger.to_dict())),
    )
    plan = await ChatDeliveryDispatcher(delivery_router=_StubRouter()).resolve_delivery_plan(context)
    assert plan.targets == (
        EndpointRef(None, "chat_sse", "s1"), *(EndpointRef.from_dict(value) for value in selected), origin,
    )


@pytest.mark.asyncio
async def test_final_delivery_reuses_committed_targets_and_content(runtime_paths_with_schema):
    from tests.chat.test_outbound_delivery import seed
    from magi.delivery.worker import DeliveryWorker
    from magi_plugin_sdk.delivery import DeliveryContent

    store, _, _ = await seed(runtime_paths_with_schema)
    received = []

    async def send(target, content):
        received.append((target, content))
        return DeliveryReceipt(target.channel_type, "receipt", 201, target.magi_session_id, content.delivery_id)

    sender = SimpleNamespace(supports_idempotent_delivery=False, deliver=send)
    registry = SimpleNamespace(get=lambda _key: sender)
    worker = DeliveryWorker(outbox=store, resolve=registry.get, clock_ms=lambda: 200)
    dispatcher = ChatDeliveryDispatcher.from_registry(channel_registry=registry, outbox=store)
    context = SimpleNamespace(session_id="s1", user_id="u1", session_run_id="", user_prefs={
        "delivery_targets": [EndpointRef("another", "telegram", "stranger").to_dict()],
    })
    for _ in range(2):
        result = await dispatcher.deliver_final_response(SimpleNamespace(context=context), response_text="changed",
            content=DeliveryContent("changed", message_id="m1"), exclude_chat_sse=True)
        assert result.pending
        assert not result.failures
    assert not received
    await worker.run_once()
    assert len(received) == 1
    target, content = received[0]
    assert target.external_chat_id == "group" and target.external_thread_id == "0"
    assert content.text == "hello"
