"""Ask→channel egress (control-event driven external fanout).

Pins the contract introduced to fix the bug where a question raised mid-turn
(``ask_user_question``) during a channel-originated run never reached the
external channel — the user could neither see nor answer it, so the turn
blocked until timeout. Desktop got chips + a transcript card; WeChat/Telegram
got nothing.

* ``build_ask_fanout_targets`` — external origin channel only (desktop already
  has chips + the ask_request card); empty for desktop-only / orphan sessions.
* ``format_ask_for_channel`` — question + numbered options + a reply hint.
* ``deliver_ask_to_channel`` — resolve the session's origin channel and deliver
  (no-op for desktop-only sessions).
* ``AskFanoutSubscriber`` listens for ``CONTROL_ASK_REQUESTED`` and fans out
  only the newly-opened pending ask.

The inbound answer round-trip is NOT tested here — it already works via
``chat.ingress._resolve_pending_ask_response`` (a text reply on the
session resolves the broker before any new turn starts).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from magi.channels import ask_fanout as ask_fanout_module
from magi.channels.ask_fanout import (
    AskChannelDeliveryError,
    AskFanoutSubscriber,
    build_ask_fanout_targets,
    deliver_ask_to_channel,
    format_ask_for_channel,
)
from magi.delivery.contracts import (
    DeliveryFailure,
    DeliveryFanoutResult,
)
from magi.events.domain_payloads import AskSnapshot, ControlAskRequested
from magi.events.events import Event, EventTypes
from magi_plugin_sdk.delivery import DeliveryReceipt


# --- pure: target resolution ------------------------------------------------

def test_no_origin_returns_empty() -> None:
    assert build_ask_fanout_targets(
        session_id="sess-1", user_id="local_user", origin_channel=None,
    ) == []


def test_chat_sse_origin_returns_empty() -> None:
    """Desktop-originated turn — desktop already has chips + card, no fanout."""
    assert build_ask_fanout_targets(
        session_id="sess-1", user_id="local_user", origin_channel="chat_sse",
    ) == []


def test_weixin_origin_returns_single_external_target() -> None:
    targets = build_ask_fanout_targets(
        session_id="sess-1", user_id="local_user", origin_channel="weixin",
    )
    assert [t.channel_type for t in targets] == ["weixin"]
    assert targets[0].magi_session_id == "sess-1"
    assert targets[0].magi_user_id == "local_user"
    assert targets[0].external_chat_id == ""  # plugin resolves at deliver time


def test_blank_origin_normalized_to_empty() -> None:
    for blank in ("", "   "):
        assert build_ask_fanout_targets(
            session_id="sess-1", user_id="local_user", origin_channel=blank,
        ) == []


def test_orphan_no_session_returns_empty() -> None:
    assert build_ask_fanout_targets(
        session_id=None, user_id="local_user", origin_channel="weixin",
    ) == []


# --- pure: text formatting --------------------------------------------------

def test_format_includes_question_and_numbered_options() -> None:
    text = format_ask_for_channel(
        "目录不存在,怎么办?", ["提供正确路径", "创建示例", "取消任务"],
    )
    assert "目录不存在,怎么办?" in text
    assert "1. 提供正确路径" in text
    assert "2. 创建示例" in text
    assert "3. 取消任务" in text


def test_format_without_options_is_just_question_plus_hint() -> None:
    text = format_ask_for_channel("继续吗?", [])
    assert text.startswith("继续吗?")
    assert "1." not in text


# --- deliver: lookup → target → fanout --------------------------------------

class _FakeRouter:
    def __init__(
        self,
        results: list[DeliveryFanoutResult] | None = None,
    ) -> None:
        self.calls: list = []
        self.results = list(results or [])

    async def fanout_deliver(self, *, content, targets):
        self.calls.append((content, targets))
        if self.results:
            return self.results.pop(0)
        return DeliveryFanoutResult(
            receipts=(
                DeliveryReceipt(
                    channel_id=targets[0].channel_type,
                    external_message_id="ask-1",
                    delivered_at_ms=1,
                ),
            )
        )


def _failed_result(channel_type: str = "weixin") -> DeliveryFanoutResult:
    target = build_ask_fanout_targets(
        session_id="sess-1",
        user_id="local_user",
        origin_channel=channel_type,
    )[0]
    return DeliveryFanoutResult(
        failures=(
            DeliveryFailure(
                target=target,
                error=RuntimeError("channel unavailable"),
                delivery_attempted=True,
            ),
        )
    )


def _mapper_returning(channel_type):
    class _Mapping:
        pass

    class _Mapper:
        async def lookup_by_session(self, _sid):
            if channel_type is None:
                return None
            m = _Mapping()
            m.channel_type = channel_type
            return m

    return _Mapper()


@pytest.mark.asyncio
async def test_deliver_ask_to_channel_delivers_to_mapped_channel() -> None:
    router = _FakeRouter()
    await deliver_ask_to_channel(
        session_id="sess-1",
        user_id="local_user",
        question="目录不存在,怎么办?",
        options=["提供正确路径", "取消任务"],
        session_mapper=_mapper_returning("weixin"),
        delivery_router=router,
        default_user_id="local_user",
    )
    assert len(router.calls) == 1
    content, targets = router.calls[0]
    assert [t.channel_type for t in targets] == ["weixin"]
    assert "目录不存在,怎么办?" in content.text
    assert "1. 提供正确路径" in content.text


@pytest.mark.asyncio
async def test_deliver_ask_to_channel_noop_for_desktop_only_session() -> None:
    router = _FakeRouter()
    await deliver_ask_to_channel(
        session_id="sess-1",
        user_id="local_user",
        question="Q?",
        options=[],
        session_mapper=_mapper_returning(None),  # no channel mapping
        delivery_router=router,
        default_user_id="local_user",
    )
    assert router.calls == []


@pytest.mark.asyncio
async def test_deliver_ask_to_channel_surfaces_router_failure() -> None:
    router = _FakeRouter(results=[_failed_result()])

    with pytest.raises(AskChannelDeliveryError, match="channel unavailable"):
        await deliver_ask_to_channel(
            session_id="sess-1",
            user_id="local_user",
            question="Q?",
            options=[],
            session_mapper=_mapper_returning("weixin"),
            delivery_router=router,
            default_user_id="local_user",
        )


# --- integration: event subscriber fans out open ask events -----------------


class _FakeBus:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, object]] = []
        self.unsubscribed: list[str] = []

    async def subscribe(self, event_type, handler):
        self.subscriptions.append((event_type, handler))
        return f"sub-{len(self.subscriptions)}"

    async def unsubscribe(self, sub_id):
        self.unsubscribed.append(sub_id)
        return True


def _ask_event(
    *,
    status: str = "pending",
    request_id: str = "ask-1",
    expires_at: float = 10_000_000_000.0,
) -> Event:
    return Event(
        type=EventTypes.CONTROL_ASK_REQUESTED,
        data=ControlAskRequested(
            session_id="sess-1",
            user_id="local_user",
            turn_id="turn-1",
            ask=AskSnapshot(
                request_id=request_id,
                question="目录不存在,怎么办?",
                options=("提供正确路径", "取消任务"),
                allow_free_text=True,
                asked_at=1.0,
                timeout_seconds=30,
                expires_at=expires_at,
                answered_at=None,
                answer=None,
                resolution=None,
                status=status,
            ),
            background=False,
        ),
    )


@pytest.mark.asyncio
async def test_ask_fanout_subscriber_delivers_pending_ask_event() -> None:
    bus = _FakeBus()
    router = _FakeRouter()
    subscriber = AskFanoutSubscriber(
        event_bus=bus,
        session_mapper=_mapper_returning("weixin"),
        delivery_router=router,
        default_user_id="local_user",
    )

    await subscriber.start()
    assert [event_type for event_type, _ in bus.subscriptions] == [
        EventTypes.CONTROL_ASK_REQUESTED
    ]

    handler = bus.subscriptions[0][1]
    await handler(_ask_event())
    await subscriber.drain()

    assert len(router.calls) == 1
    content, targets = router.calls[0]
    assert [target.channel_type for target in targets] == ["weixin"]
    assert "目录不存在,怎么办?" in content.text


@pytest.mark.asyncio
async def test_ask_fanout_waits_for_clear_and_rechecks_the_session_mapping() -> None:
    class _MutableMapper:
        def __init__(self) -> None:
            self.channel_type: str | None = "weixin"

        async def lookup_by_session(self, _session_id):
            if self.channel_type is None:
                return None
            return type("_Mapping", (), {"channel_type": self.channel_type})()

    bus = _FakeBus()
    router = _FakeRouter()
    mapper = _MutableMapper()
    subscriber = AskFanoutSubscriber(
        event_bus=bus,
        session_mapper=mapper,
        delivery_router=router,
        default_user_id="local_user",
    )
    await subscriber.start()
    handler = bus.subscriptions[0][1]

    async with subscriber.conversation_clear_boundary():
        await handler(_ask_event())
        await asyncio.sleep(0)
        assert router.calls == []
        mapper.channel_type = None

    await subscriber.drain()
    assert router.calls == []


@pytest.mark.asyncio
async def test_ask_fanout_stops_when_global_conversation_clear_is_pending() -> None:
    bus = _FakeBus()
    router = _FakeRouter()
    delivery_allowed = AsyncMock(return_value=False)
    subscriber = AskFanoutSubscriber(
        event_bus=bus,
        session_mapper=_mapper_returning("weixin"),
        delivery_router=router,
        default_user_id="local_user",
        delivery_allowed=delivery_allowed,
    )
    await subscriber.start()
    handler = bus.subscriptions[0][1]

    await handler(_ask_event())
    await subscriber.drain()

    delivery_allowed.assert_awaited_once()
    assert router.calls == []


@pytest.mark.asyncio
async def test_ask_fanout_subscriber_suppresses_duplicate_pending_event() -> None:
    bus = _FakeBus()
    router = _FakeRouter()
    subscriber = AskFanoutSubscriber(
        event_bus=bus,
        session_mapper=_mapper_returning("weixin"),
        delivery_router=router,
        default_user_id="local_user",
    )

    await subscriber.start()
    handler = bus.subscriptions[0][1]
    await handler(_ask_event())
    await handler(_ask_event())
    await subscriber.drain()
    await handler(_ask_event())
    await subscriber.drain()

    assert len(router.calls) == 1


@pytest.mark.asyncio
async def test_ask_fanout_subscriber_skips_expired_pending_event() -> None:
    bus = _FakeBus()
    router = _FakeRouter()
    subscriber = AskFanoutSubscriber(
        event_bus=bus,
        session_mapper=_mapper_returning("weixin"),
        delivery_router=router,
        default_user_id="local_user",
        now_seconds=lambda: 100.0,
    )

    await subscriber.start()
    handler = bus.subscriptions[0][1]
    await handler(_ask_event(expires_at=99.0))
    await subscriber.drain()

    assert router.calls == []
    assert len(subscriber._recent_request_ids) == 0


@pytest.mark.asyncio
async def test_ask_fanout_dedup_prunes_expired_entries() -> None:
    now = [100.0]
    bus = _FakeBus()
    router = _FakeRouter()
    subscriber = AskFanoutSubscriber(
        event_bus=bus,
        session_mapper=_mapper_returning("weixin"),
        delivery_router=router,
        default_user_id="local_user",
        now_seconds=lambda: now[0],
    )

    await subscriber.start()
    handler = bus.subscriptions[0][1]
    await handler(_ask_event(request_id="ask-old", expires_at=200.0))
    await subscriber.drain()
    assert list(subscriber._recent_request_ids) == ["ask-old"]

    now[0] = 201.0
    await handler(_ask_event(request_id="ask-new", expires_at=300.0))
    await subscriber.drain()

    assert list(subscriber._recent_request_ids) == ["ask-new"]
    assert len(router.calls) == 2


@pytest.mark.asyncio
async def test_ask_fanout_dedup_has_bounded_lru_capacity() -> None:
    bus = _FakeBus()
    router = _FakeRouter()
    subscriber = AskFanoutSubscriber(
        event_bus=bus,
        session_mapper=_mapper_returning("weixin"),
        delivery_router=router,
        default_user_id="local_user",
        max_dedup_entries=2,
        now_seconds=lambda: 100.0,
    )

    await subscriber.start()
    handler = bus.subscriptions[0][1]
    for request_id in ("ask-1", "ask-2", "ask-3"):
        await handler(
            _ask_event(
                request_id=request_id,
                expires_at=1_000.0,
            )
        )
    await subscriber.drain()

    assert list(subscriber._recent_request_ids) == ["ask-2", "ask-3"]
    assert len(router.calls) == 3

    # Capacity eviction deliberately favors bounded memory over suppressing
    # a very late duplicate that has fallen out of the process-local LRU.
    await handler(_ask_event(request_id="ask-1", expires_at=1_000.0))
    await subscriber.drain()
    assert len(subscriber._recent_request_ids) == 2
    assert len(router.calls) == 4


@pytest.mark.asyncio
async def test_ask_fanout_subscriber_ignores_closed_ask_event() -> None:
    bus = _FakeBus()
    router = _FakeRouter()
    subscriber = AskFanoutSubscriber(
        event_bus=bus,
        session_mapper=_mapper_returning("weixin"),
        delivery_router=router,
        default_user_id="local_user",
    )

    await subscriber.start()
    handler = bus.subscriptions[0][1]
    await handler(_ask_event(status="timeout"))
    await subscriber.drain()

    assert router.calls == []


@pytest.mark.asyncio
async def test_ask_fanout_subscriber_does_not_retry_ambiguous_delivery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict]] = []

    async def _publish(channel, payload, **_kwargs):
        published.append((channel, payload))

    monkeypatch.setattr(
        ask_fanout_module.control_events,
        "publish_control_event",
        _publish,
    )
    bus = _FakeBus()
    router = _FakeRouter(
        results=[
            _failed_result(),
            DeliveryFanoutResult(
                receipts=(
                    DeliveryReceipt(
                        channel_id="weixin",
                        external_message_id="ask-2",
                        delivered_at_ms=2,
                    ),
                )
            ),
        ]
    )
    subscriber = AskFanoutSubscriber(
        event_bus=bus,
        session_mapper=_mapper_returning("weixin"),
        delivery_router=router,
        default_user_id="local_user",
    )

    await subscriber.start()
    handler = bus.subscriptions[0][1]
    await handler(_ask_event())
    await subscriber.drain()

    assert len(router.calls) == 1
    assert published[0][0] == "control.ask.delivery_failed"
    assert published[0][1]["automatic_retry"] is False


@pytest.mark.asyncio
async def test_ask_fanout_subscriber_publishes_exhausted_delivery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, dict]] = []

    async def _publish(channel, payload, **_kwargs):
        published.append((channel, payload))

    monkeypatch.setattr(
        ask_fanout_module.control_events,
        "publish_control_event",
        _publish,
    )
    bus = _FakeBus()
    router = _FakeRouter(results=[_failed_result()])
    subscriber = AskFanoutSubscriber(
        event_bus=bus,
        session_mapper=_mapper_returning("weixin"),
        delivery_router=router,
        default_user_id="local_user",
    )

    await subscriber.start()
    handler = bus.subscriptions[0][1]
    await handler(_ask_event())
    await subscriber.drain()

    assert published == [
        (
            "control.ask.delivery_failed",
            {
                "request_id": "ask-1",
                "session_id": "sess-1",
                "error": (
                    "Ask delivery failed for channel 'weixin': "
                    "channel unavailable"
                ),
                "delivery_attempts": 1,
                "automatic_retry": False,
            },
        )
    ]
