"""Ask→channel egress (lightweight external fanout).

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
* ``_HostInteractionPort.ask`` invokes the bound fanout callback exactly once
  when the ask opens, and still works when no callback is bound.

The inbound answer round-trip is NOT tested here — it already works via
``chat.ingress._resolve_pending_ask_response`` (a text reply on the
session resolves the broker before any new turn starts).
"""
from __future__ import annotations

import asyncio
import contextlib

import pytest

from magi.control.common import InteractionBroker
from magi.control.session_store import ControlSessionStore
from magi.bootstrap.tool_capabilities import _HostInteractionPort
from magi.core.container import get_container
from magi.control.common.ask_fanout import (
    bind_ask_fanout_callback,
    build_ask_fanout_targets,
    deliver_ask_to_channel,
    format_ask_for_channel,
    get_ask_fanout_callback,
    reset_ask_fanout_callback,
)


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


# --- integration: ask port invokes the fanout callback on open -------------

@contextlib.contextmanager
def _override(**bindings):
    container = get_container()
    providers = {k: getattr(container, k) for k in bindings}
    for key, value in bindings.items():
        providers[key].override(value)
    try:
        yield container
    finally:
        for key in bindings:
            providers[key].reset_override()


@pytest.fixture(autouse=True)
def _clear_binding():
    reset_ask_fanout_callback()
    yield
    reset_ask_fanout_callback()


async def _answer_when_open(store, broker, session_id, answer="取消任务") -> None:
    for _ in range(50):
        ask = store.ask_state(session_id)
        if ask is not None:
            await broker.resolve(
                interaction_id=ask.request_id, kind="ask", response=answer,
            )
            return
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_ask_invokes_fanout_callback_on_open() -> None:
    store = ControlSessionStore()
    broker = InteractionBroker()
    calls: list[dict] = []

    async def _record(**kwargs):
        calls.append(kwargs)

    bind_ask_fanout_callback(_record)

    with _override(control_session_store=store, control_interaction_broker=broker):
        port = _HostInteractionPort()
        answerer = asyncio.create_task(_answer_when_open(store, broker, "sid-ask"))
        outcome = await port.ask(
            session_id="sid-ask",
            user_id="local_user",
            turn_id="turn-1",
            question="目录不存在,怎么办?",
            options=["提供正确路径", "取消任务"],
            allow_free_text=True,
            timeout_seconds=5,
        )
        await answerer

    assert outcome.answered is True
    assert len(calls) == 1
    assert calls[0]["session_id"] == "sid-ask"
    assert calls[0]["question"] == "目录不存在,怎么办?"
    assert calls[0]["options"] == ["提供正确路径", "取消任务"]
    assert calls[0].get("request_id")


@pytest.mark.asyncio
async def test_ask_without_bound_callback_does_not_raise() -> None:
    """Desktop-only deployments (no channels module bound) — ask still works."""
    store = ControlSessionStore()
    broker = InteractionBroker()
    assert get_ask_fanout_callback() is None  # cleared by autouse fixture

    with _override(control_session_store=store, control_interaction_broker=broker):
        port = _HostInteractionPort()
        answerer = asyncio.create_task(_answer_when_open(store, broker, "sid-x", "ok"))
        outcome = await port.ask(
            session_id="sid-x",
            user_id="local_user",
            turn_id="t",
            question="Q?",
            options=[],
            allow_free_text=True,
            timeout_seconds=5,
        )
        await answerer
    assert outcome.answered is True
