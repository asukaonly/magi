"""Unified host control-command port — composes permission + session + help."""
from __future__ import annotations

from contextlib import asynccontextmanager
import pytest

from magi.channels.control_commands import HostControlPort
from magi.control.common.interaction_broker import InteractionBroker
from magi.control.permission.brokered_prompter import PendingPermissionRegistry
from magi.control.permission.contracts import PermissionRequest, RiskLevel, ToolOrigin
from magi_plugin_sdk.channels import (
    ChannelInboundContext,
    ChannelProviderTimeEvidence,
    ChannelSessionMapping,
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


class _FakeMapper:
    def __init__(self, mapping: ChannelSessionMapping | None) -> None:
        self._mapping = mapping
        self.deleted: list[tuple[str, str]] = []

    async def lookup_by_session(self, _session_id):
        return self._mapping

    async def delete_mapping(self, channel_type, external_chat_id):
        self.deleted.append((channel_type, external_chat_id))


def _make_request(*, session_id="s1") -> PermissionRequest:
    return PermissionRequest(
        request_id=PermissionRequest.new_id(),
        tool_name="image_gen",
        arguments={},
        risk_level=RiskLevel.MEDIUM,
        origin=ToolOrigin.CHAT,
        agent_id="agent",
        session_id=session_id,
        turn_id=None,
        workspace=None,
    )


def _port(*, mapper=None, registry=None, broker=None) -> HostControlPort:
    return HostControlPort(
        ingress_boundary=_AllowingBoundary(),  # type: ignore[arg-type]
        session_mapper=mapper, permission_registry=registry, interaction_broker=broker,
    )


def _mapping() -> ChannelSessionMapping:
    return ChannelSessionMapping("weixin", "chat-1", "sess-1", "local_user")


@pytest.mark.asyncio
async def test_session_command_returns_session_result() -> None:
    mapper = _FakeMapper(_mapping())
    port = _port(mapper=mapper)
    r = await port.handle_command(
        inbound_context=_INBOUND_CONTEXT,
        message="/新会话", session_id="sess-1",
        channel_type="weixin", external_chat_id="chat-1", external_user_id="u",
    )
    assert r is not None and r.kind == "session" and r.ack
    assert mapper.deleted == [("weixin", "chat-1")]


@pytest.mark.asyncio
async def test_permission_command_returns_permission_result() -> None:
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    await registry.add(_make_request(session_id="s1"))
    port = _port(registry=registry, broker=broker)
    r = await port.handle_command(
        inbound_context=_INBOUND_CONTEXT,
        message="/approve", session_id="s1",
        channel_type="weixin", external_chat_id="c", external_user_id="u",
    )
    assert r is not None and r.kind == "permission" and r.ack


@pytest.mark.asyncio
async def test_help_returns_help_result() -> None:
    port = _port()
    r = await port.handle_command(
        inbound_context=_INBOUND_CONTEXT,
        message="/help", session_id="s1",
        channel_type="weixin", external_chat_id="c", external_user_id="u",
    )
    assert r is not None and r.kind == "help" and "/new" in r.ack


@pytest.mark.asyncio
async def test_non_command_returns_none() -> None:
    mapper = _FakeMapper(_mapping())
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    port = _port(mapper=mapper, registry=registry, broker=broker)
    r = await port.handle_command(
        inbound_context=_INBOUND_CONTEXT,
        message="今天天气怎么样", session_id="sess-1",
        channel_type="weixin", external_chat_id="c", external_user_id="u",
    )
    assert r is None
    assert mapper.deleted == []


@pytest.mark.asyncio
async def test_session_works_when_permission_deps_absent() -> None:
    """No registry/broker (degraded) — permission family skipped, session still works."""
    mapper = _FakeMapper(_mapping())
    port = _port(mapper=mapper)
    r = await port.handle_command(
        inbound_context=_INBOUND_CONTEXT,
        message="/reset", session_id="sess-1",
        channel_type="weixin", external_chat_id="chat-1", external_user_id="u",
    )
    assert r is not None and r.kind == "session"
