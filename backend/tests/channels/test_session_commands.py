"""Channel `/新会话` (new-session) command parser + handler + dispatcher wiring.

Pins:
* Slash forms (`/new` `/reset` `/新会话` `/重置`, case-insensitive, whole-message)
  and exact Chinese phrases (`新会话` `新对话` `重新开始` `重置会话`) match.
* Substring / extra text / empty do NOT match (whole-message only) → dispatch to LLM.
* On match with a channel mapping → `delete_mapping(channel_type, external_chat_id)`
  (resolved via `lookup_by_session`) + handled=True + ack; the NEXT message then
  starts a fresh session via `resolve_or_create`.
* No mapping (already reset / non-channel) → idempotent ack, no delete.
* No session_mapper / no session_id → handled=False (safe pass-through).
* Dispatcher: a matched command short-circuits (no LLM dispatch), returns the ack;
  a normal message dispatches as usual.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from magi.channels.session_commands import (
    SessionCommandOutcome,
    is_new_session_command,
    try_handle_session_command,
)
from magi_plugin_sdk.channels import (
    ChannelInboundClearStrategy,
    ChannelInboundContext,
    ChannelProviderTimeEvidence,
)


class _AllowingBoundary:
    @asynccontextmanager
    async def operation(self, _context, **_kwargs):
        yield


_INBOUND_CONTEXT = ChannelInboundContext(
    channel_type="telegram",
    stream_id="account-1",
    admission_evidence=ChannelProviderTimeEvidence(provider_occurred_at_ms=1),
    clear_generation=0,
)


class _FakeMapping:
    def __init__(self, channel_type: str, external_chat_id: str) -> None:
        self.channel_type = channel_type
        self.external_chat_id = external_chat_id


class _FakeMapper:
    def __init__(self, mapping: _FakeMapping | None) -> None:
        self._mapping = mapping
        self.deleted: list[tuple[str, str]] = []

    async def lookup_by_session(self, _session_id: str):
        return self._mapping

    async def delete_mapping(self, channel_type: str, external_chat_id: str) -> None:
        self.deleted.append((channel_type, external_chat_id))


# === parser ================================================================

@pytest.mark.parametrize(
    "text",
    ["/new", "/reset", "/新会话", "/重置", "  /new  ", "/NEW", "/Reset",
     "新会话", "新对话", "重新开始", "重置会话", "  新会话 "],
)
def test_matches_new_session_command(text: str) -> None:
    assert is_new_session_command(text) is True


@pytest.mark.parametrize(
    "text",
    ["", "   ", "hello", "我想开个新会话", "新会话啊", "帮我新会话",
     "yes /new please", "/newsession", "/news", "approve", "/approve"],
)
def test_does_not_match_non_command(text: str) -> None:
    assert is_new_session_command(text) is False


# === handler ===============================================================

@pytest.mark.asyncio
async def test_handler_deletes_mapping_on_match() -> None:
    mapper = _FakeMapper(_FakeMapping("weixin", "chat-abc@im.wechat"))
    out = await try_handle_session_command(
        message="/新会话", session_id="chsess_x", session_mapper=mapper,
    )
    assert out.handled is True
    assert out.ack_message
    assert mapper.deleted == [("weixin", "chat-abc@im.wechat")]


@pytest.mark.asyncio
async def test_handler_idempotent_when_no_mapping() -> None:
    """Already reset / not channel-bound — ack, but no delete attempted."""
    mapper = _FakeMapper(None)
    out = await try_handle_session_command(
        message="新会话", session_id="chsess_x", session_mapper=mapper,
    )
    assert out.handled is True
    assert out.ack_message
    assert mapper.deleted == []


@pytest.mark.asyncio
async def test_handler_passes_through_non_command() -> None:
    mapper = _FakeMapper(_FakeMapping("weixin", "c"))
    out = await try_handle_session_command(
        message="今天天气怎么样", session_id="chsess_x", session_mapper=mapper,
    )
    assert out.handled is False
    assert mapper.deleted == []


@pytest.mark.asyncio
async def test_handler_no_mapper_is_passthrough() -> None:
    out = await try_handle_session_command(
        message="/新会话", session_id="chsess_x", session_mapper=None,
    )
    assert out.handled is False


@pytest.mark.asyncio
async def test_handler_no_session_id_is_passthrough() -> None:
    mapper = _FakeMapper(_FakeMapping("weixin", "c"))
    out = await try_handle_session_command(
        message="/新会话", session_id=None, session_mapper=mapper,
    )
    assert out.handled is False
    assert mapper.deleted == []


# === dispatcher wiring =====================================================

@pytest.mark.asyncio
async def test_dispatcher_short_circuits_new_session(monkeypatch) -> None:
    """A matched command must NOT reach the LLM dispatch; returns the ack."""
    from magi.channels import dispatcher as dispatcher_mod

    called: list[str] = []

    async def _spy_dispatch(**kwargs):  # noqa: ANN003
        called.append(kwargs.get("message", ""))
        return SimpleNamespace(
            success=True, user_id="u", session_id="chsess_x", turn_id="t",
            message_id="m", error_code=None, error_message=None, queue_size=0,
        )

    mapper = _FakeMapper(_FakeMapping("weixin", "chat-abc@im.wechat"))
    disp = dispatcher_mod.ChannelMessageDispatcher(
        channel_type="weixin",
        inbound_clear_strategy=ChannelInboundClearStrategy.PROVIDER_TIME,
        ingress_boundary=_AllowingBoundary(),  # type: ignore[arg-type]
        session_mapper=mapper,
        message_dispatcher=_spy_dispatch,
    )
    outcome = await disp.dispatch_user_message(
        inbound_context=_INBOUND_CONTEXT,
        source="weixin", user_id="u", message="/新会话", session_id="chsess_x",
    )

    assert called == []  # LLM dispatch NOT invoked
    assert outcome.success is True
    assert outcome.turn_id is None
    assert outcome.error_message  # ack carried back to the channel
    assert mapper.deleted == [("weixin", "chat-abc@im.wechat")]


@pytest.mark.asyncio
async def test_dispatcher_dispatches_normal_message(monkeypatch) -> None:
    from magi.channels import dispatcher as dispatcher_mod

    called: list[str] = []

    async def _spy_dispatch(**kwargs):  # noqa: ANN003
        called.append(kwargs.get("message", ""))
        return SimpleNamespace(
            success=True, user_id="u", session_id="chsess_x", turn_id="t",
            message_id="m", error_code=None, error_message=None, queue_size=0,
        )

    mapper = _FakeMapper(_FakeMapping("weixin", "c"))
    disp = dispatcher_mod.ChannelMessageDispatcher(
        channel_type="weixin",
        inbound_clear_strategy=ChannelInboundClearStrategy.PROVIDER_TIME,
        ingress_boundary=_AllowingBoundary(),  # type: ignore[arg-type]
        session_mapper=mapper,
        message_dispatcher=_spy_dispatch,
    )
    outcome = await disp.dispatch_user_message(
        inbound_context=_INBOUND_CONTEXT,
        source="weixin", user_id="u", message="今天天气怎么样", session_id="chsess_x",
    )

    assert called == ["今天天气怎么样"]  # normal dispatch happened
    assert outcome.success is True
    assert mapper.deleted == []


def test_outcome_shape() -> None:
    assert SessionCommandOutcome(handled=False).ack_message is None
    assert SessionCommandOutcome(handled=True, ack_message="x").ack_message == "x"
