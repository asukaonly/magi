"""``BrokeredPermissionPrompter`` fanout_callback hook — CF-5 piece.

Pins:
* Constructor takes optional ``fanout_callback`` alongside the
  existing ``notify_callback``. Both fire on every prompt.
* ``bind_fanout_callback`` late-binds after construction (used by
  ChannelsModule which can't know the registry at ControlPlane init
  time).
* Fanout exceptions are swallowed (same best-effort policy as
  notify_callback) — desktop / broker.wait must not be blocked by
  a misbehaving plugin channel.
* Default timeout bump 120 → 300s in PermissionGateway is verified
  by the gateway's default param value.
"""
from __future__ import annotations

import pytest

from magi.control.common.interaction_broker import InteractionBroker
from magi.control.permission.brokered_prompter import (
    BrokeredPermissionPrompter,
    PendingPermissionRegistry,
)
from magi.control.permission.contracts import (
    PermissionRequest,
    RiskLevel,
    ToolOrigin,
)
from magi.control.permission.gateway import PermissionGateway, UserPromptResponse


def _make_request(*, session_id: str = "s1") -> PermissionRequest:
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


async def _make_allowed(broker: InteractionBroker, request_id: str) -> None:
    """Drive the broker out-of-band so the prompter awaits and resolves."""
    await broker.resolve(
        interaction_id=request_id,
        kind="permission",
        response=UserPromptResponse(allow=True, scope=None, matcher=None, note=None),
    )


# === fanout_callback wiring ==============================================


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", ["constructor", "late", "disabled"])
async def test_fanout_binding_controls_callback_delivery(binding):
    import asyncio
    from unittest.mock import AsyncMock

    broker = InteractionBroker()
    registry = PendingPermissionRegistry()
    fanout = AsyncMock()
    prompter = BrokeredPermissionPrompter(
        broker=broker,
        registry=registry,
        fanout_callback=None if binding == "late" else fanout,
    )
    if binding == "late":
        prompter.bind_fanout_callback(fanout)
    elif binding == "disabled":
        prompter.bind_fanout_callback(None)
    req = _make_request()
    resolver = asyncio.create_task(_make_allowed(broker, req.request_id))
    response = await prompter(req, timeout_seconds=2.0)
    await resolver
    assert response.allow is True
    if binding == "disabled":
        fanout.assert_not_awaited()
    else:
        fanout.assert_awaited_once_with(req)


@pytest.mark.asyncio
async def test_fanout_callback_exception_does_not_block_prompt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If fanout_callback raises (misbehaving plugin channel), the
    broker.wait still proceeds — desktop path is unaffected. Failure
    logged at WARNING level."""
    broker = InteractionBroker()
    registry = PendingPermissionRegistry()

    async def fanout(req):
        raise RuntimeError("fanout boom")

    prompter = BrokeredPermissionPrompter(
        broker=broker, registry=registry, fanout_callback=fanout,
    )
    req = _make_request()
    import asyncio
    resolver = asyncio.create_task(_make_allowed(broker, req.request_id))
    with caplog.at_level("WARNING"):
        response = await prompter(req, timeout_seconds=2.0)
    await resolver
    assert response.allow is True
    assert any("fanout_failed" in rec.message for rec in caplog.records)


# === Gateway default timeout bump ========================================
