"""Question egress is recovered from the owner transaction, not bus payloads."""
from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from magi_plugin_sdk.channels import ChannelSessionMapping
from magi_plugin_sdk.delivery import DeliveryReceipt

from magi.channels.ask_fanout import AskFanoutSubscriber, format_ask_for_channel
from magi.delivery.senders import MessageDeliverySender
from magi.control.session_store import ControlSessionStore
from magi.core.sqlite import sqlite_connection_async


@pytest.fixture
async def setup_delivery(tmp_path, ensure_db_schema):
    path = tmp_path / "runtime.db"
    ensure_db_schema("runtime_trace", path)
    store = ControlSessionStore(db_path=path)
    await store.initialize()
    mapping = ChannelSessionMapping("account:telegram", "room", "session", "local_user", external_thread_id="topic")
    mapper = SimpleNamespace(lookup_by_session=AsyncMock(return_value=mapping))
    sent = []

    async def deliver(target, content):
        sent.append((target, content))
        return DeliveryReceipt(target.channel_type, "provider-message", int(time.time()*1000), target.magi_session_id, content.delivery_id)

    sender = SimpleNamespace(deliver=deliver, supports_idempotent_delivery=False)
    registry = SimpleNamespace(get=lambda _: sender)
    bus = SimpleNamespace(subscribe=AsyncMock(return_value="subscription"), unsubscribe=AsyncMock())
    subscriber = AskFanoutSubscriber(event_bus=bus, session_mapper=mapper, channel_registry=registry,
        session_store=store, default_user_id="local_user")
    return SimpleNamespace(path=path, store=store, mapper=mapper, sender=sender, registry=registry,
                           bus=bus, subscriber=subscriber, sent=sent)


@pytest.mark.asyncio
async def test_event_loss_keeps_frozen_thread_and_content(setup_delivery):
    env = setup_delivery
    await env.store.open_ask("session", question="Choose", options=["first", "second"], request_id="request")
    env.mapper.lookup_by_session.return_value = replace(env.mapper.lookup_by_session.return_value,
        external_chat_id="different-room", external_thread_id="other-topic")
    # No event has been emitted. The committed record is sufficient.
    assert await env.subscriber.run_once()
    assert not await env.subscriber.run_once()
    target, content = env.sent[0]
    assert target.external_chat_id == "room" and target.external_thread_id == "topic"
    assert target.channel_type == "account:telegram"
    assert content.text == "Choose\n\n1. first\n2. second\n\n（直接回复消息作答即可）"
    assert content.delivery_id
    assert len(env.sent) == 1
    await env.subscriber._on_ask_requested(object())
    assert not await env.subscriber.run_once()


@pytest.mark.asyncio
async def test_question_and_delivery_rollback_together(setup_delivery):
    env = setup_delivery
    from magi.control.ask_contracts import AskState
    from magi.control.ask_delivery import AskDeliveryIntent
    from magi_plugin_sdk.delivery import DeliveryContent
    from magi_plugin_sdk.endpoints import EndpointRef
    from magi.control.persistence.asks import SqliteAskRepository

    repo = SqliteAskRepository(str(env.path))
    invalid = AskDeliveryIntent("u", EndpointRef("a", "telegram", "room"), DeliveryContent("q", message_payload={"invalid": object()}))
    with pytest.raises(TypeError):
        await repo.open(session_id="session", ask=AskState("bad", "q"), delivery=invalid)
    async with sqlite_connection_async(str(env.path), profile="hot_write") as db:
        assert await db.execute_fetchall("SELECT request_id FROM control_asks") == []
        assert await db.execute_fetchall("SELECT delivery_id FROM control_ask_deliveries") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["answer", "clear", "restart", "expire"])
async def test_closed_question_never_sends(setup_delivery, action):
    env = setup_delivery
    await env.store.open_ask("session", question="Continue?", request_id="r",
                             timeout_seconds=0.001 if action == "expire" else 30)
    if action == "answer":
        assert await env.store.accept_ask_answer("r", "yes")
    elif action == "clear":
        await env.store.clear_session("session")
    elif action == "restart":
        restored = ControlSessionStore(db_path=env.path)
        await restored.initialize()
        assert restored.ask_state("session").status == "cancelled"
    else:
        await asyncio.sleep(0.005)
    assert not await env.subscriber.run_once()
    assert env.sent == []


@pytest.mark.asyncio
async def test_missing_channel_retries_before_invocation_only(setup_delivery):
    env = setup_delivery
    await env.store.open_ask("session", question="q", request_id="r")
    now = int(time.time()*1000)
    env.subscriber._worker._clock = lambda: now
    env.registry.get = lambda _: None
    # The registry resolver is captured at composition; replace it explicitly.
    env.subscriber._worker._resolve = lambda _: None
    assert await env.subscriber.run_once()
    env.subscriber._worker._resolve = lambda _: MessageDeliverySender(env.sender)
    now += 6000
    assert await env.subscriber.run_once()
    assert len(env.sent) == 1


@pytest.mark.asyncio
async def test_unconfirmed_send_is_not_repeated_after_subscriber_restart(setup_delivery):
    env = setup_delivery
    env.sender.deliver = AsyncMock(side_effect=TimeoutError("Provider outcome unknown"))
    await env.store.open_ask("session", question="q", request_id="r")
    assert await env.subscriber.run_once()
    await env.subscriber.stop()
    await env.subscriber.start()
    await asyncio.sleep(0.02)
    await env.subscriber.stop()
    env.sender.deliver.assert_awaited_once()
    async with sqlite_connection_async(str(env.path), profile="hot_write") as db:
        assert [tuple(row) for row in await db.execute_fetchall("SELECT state,attempt_count FROM control_ask_deliveries")] == [("uncertain", 1)]


@pytest.mark.asyncio
async def test_clear_boundary_waits_for_inflight_question(setup_delivery):
    env = setup_delivery
    started, release, cleared = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = env.sender.deliver

    async def send(target, content):
        started.set()
        await release.wait()
        return await original(target, content)

    env.sender.deliver = send
    await env.store.open_ask("session", question="q", request_id="r")
    work = asyncio.create_task(env.subscriber.run_once())
    await started.wait()

    async def clear():
        async with env.subscriber.conversation_clear_boundary():
            await env.store.clear_session("session")
            cleared.set()

    clearing = asyncio.create_task(clear())
    await asyncio.sleep(0)
    assert not cleared.is_set()
    release.set()
    await work
    await clearing
    assert not await env.subscriber.run_once()


def test_empty_options_still_explain_reply():
    assert format_ask_for_channel("Continue?", []) == "Continue?\n\n（直接回复消息作答即可）"


@pytest.mark.asyncio
async def test_route_resolution_does_not_extend_answer_deadline(setup_delivery):
    env = setup_delivery
    await env.store.open_ask("session", question="q", timeout_seconds=30, deadline=time.time()-1)
    assert not await env.subscriber.run_once()
    assert env.sent == []
