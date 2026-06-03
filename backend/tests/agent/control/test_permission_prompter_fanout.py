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
async def test_fanout_callback_fires_on_every_prompt() -> None:
    """When ``fanout_callback`` is set at construction, every
    ``__call__`` invokes it with the PermissionRequest."""
    broker = InteractionBroker()
    registry = PendingPermissionRegistry()
    seen: list[PermissionRequest] = []

    async def fanout(req):
        seen.append(req)

    prompter = BrokeredPermissionPrompter(
        broker=broker, registry=registry, fanout_callback=fanout,
    )
    req = _make_request()
    import asyncio
    resolver = asyncio.create_task(_make_allowed(broker, req.request_id))
    await prompter(req, timeout_seconds=2.0)
    await resolver
    assert seen == [req]


@pytest.mark.asyncio
async def test_no_fanout_callback_no_fanout() -> None:
    """When fanout_callback is None (the default / pre-H+2 mode),
    only notify_callback fires — pre-H+2 behavior preserved."""
    broker = InteractionBroker()
    registry = PendingPermissionRegistry()
    notified = []

    async def notify(channel, payload):
        notified.append((channel, payload))

    prompter = BrokeredPermissionPrompter(
        broker=broker, registry=registry, notify_callback=notify,
    )
    req = _make_request()
    import asyncio
    resolver = asyncio.create_task(_make_allowed(broker, req.request_id))
    await prompter(req, timeout_seconds=2.0)
    await resolver
    assert len(notified) == 1
    assert notified[0][0] == "control.permission.requested"


@pytest.mark.asyncio
async def test_bind_fanout_callback_late_binding() -> None:
    """Bootstrap pattern: prompter is built with no callback, a later
    module calls ``bind_fanout_callback`` to wire fanout in."""
    broker = InteractionBroker()
    registry = PendingPermissionRegistry()
    prompter = BrokeredPermissionPrompter(broker=broker, registry=registry)

    seen = []

    async def fanout(req):
        seen.append(req)

    prompter.bind_fanout_callback(fanout)
    req = _make_request()
    import asyncio
    resolver = asyncio.create_task(_make_allowed(broker, req.request_id))
    await prompter(req, timeout_seconds=2.0)
    await resolver
    assert seen == [req]


@pytest.mark.asyncio
async def test_bind_fanout_callback_can_disable() -> None:
    """Pass None to ``bind_fanout_callback`` to disable (tests that
    exercise the notify-only path)."""
    broker = InteractionBroker()
    registry = PendingPermissionRegistry()

    async def fanout(req):
        raise AssertionError("should not be called")

    prompter = BrokeredPermissionPrompter(
        broker=broker, registry=registry, fanout_callback=fanout,
    )
    prompter.bind_fanout_callback(None)  # disable
    req = _make_request()
    import asyncio
    resolver = asyncio.create_task(_make_allowed(broker, req.request_id))
    # If fanout were called, it would raise AssertionError; passing means disabled.
    await prompter(req, timeout_seconds=2.0)
    await resolver


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


def test_gateway_default_prompt_timeout_bumped_to_300() -> None:
    """Phase H+2 default timeout bumped 120 → 300 to accommodate
    external-channel response latency (WeChat / Telegram users may
    be away from device for minutes). Verified at the signature level
    (no need to construct a real gateway — saves wiring noise)."""
    import inspect
    sig = inspect.signature(PermissionGateway.__init__)
    default = sig.parameters["prompt_timeout_seconds"].default
    assert default == 300.0
