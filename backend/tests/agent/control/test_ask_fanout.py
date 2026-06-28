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

import pytest

from magi.channels.ask_fanout import (
    AskFanoutSubscriber,
    build_ask_fanout_targets,
    deliver_ask_to_channel,
    format_ask_for_channel,
)
from magi.events.domain_payloads import AskSnapshot, ControlAskRequested
from magi.events.events import Event, EventTypes


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
    def __init__(self) -> None:
        self.calls: list = []

    async def fanout_deliver(self, *, content, targets):
        self.calls.append((content, targets))
        return []


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


def _ask_event(*, status: str = "pending") -> Event:
    return Event(
        type=EventTypes.CONTROL_ASK_REQUESTED,
        data=ControlAskRequested(
            session_id="sess-1",
            user_id="local_user",
            turn_id="turn-1",
            ask=AskSnapshot(
                request_id="ask-1",
                question="目录不存在,怎么办?",
                options=("提供正确路径", "取消任务"),
                allow_free_text=True,
                asked_at=1.0,
                timeout_seconds=30,
                expires_at=31.0,
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
