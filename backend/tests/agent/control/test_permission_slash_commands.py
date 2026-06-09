"""``try_handle_control_command`` parser + broker resolution — CF-6.

Pins:
* Non-slash messages pass through (handled=False) → dispatcher
  continues to LLM.
* ``/approve <short_id>`` resolves a matching pending request with
  ``allow=True``; broker.resolve called with the full request_id.
* ``/deny <short_id>`` resolves with ``allow=False``; same path.
* Aliases ``/allow`` ``/reject`` work.
* Case-insensitive verb.
* Cross-session isolation enforced via registry.
* No matching request → handled=True with a friendly ack_message,
  broker.resolve NOT called.
* Hybrid "hello /approve abc" must NOT match (only whole-message
  commands).
"""
from __future__ import annotations

import pytest

from magi.control.common.interaction_broker import InteractionBroker
from magi.control.permission.brokered_prompter import PendingPermissionRegistry
from magi.control.permission.contracts import (
    PermissionRequest,
    RiskLevel,
    ToolOrigin,
)
from magi.control.permission.gateway import UserPromptResponse
from magi.control.permission.slash_commands import try_handle_control_command


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


# === Non-command pass-through ============================================


@pytest.mark.asyncio
async def test_plain_chat_is_not_a_command() -> None:
    """No slash → handled=False → dispatcher continues to LLM."""
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    out = await try_handle_control_command(
        message="please draw a cat",
        session_id="s1", registry=registry, broker=broker,
    )
    assert out.handled is False


@pytest.mark.asyncio
async def test_slash_inside_message_is_not_a_command() -> None:
    """Slash command is only matched as the WHOLE message. ``"yes
    /approve abc123 please"`` is chat, not a command."""
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    out = await try_handle_control_command(
        message="yes /approve abc123 please",
        session_id="s1", registry=registry, broker=broker,
    )
    assert out.handled is False


@pytest.mark.asyncio
async def test_unknown_slash_command_is_not_handled() -> None:
    """``/help`` / ``/foo`` aren't approval commands → fall through.
    (Future issue #5 may handle them; not in CF-6 scope.)"""
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    out = await try_handle_control_command(
        message="/help",
        session_id="s1", registry=registry, broker=broker,
    )
    assert out.handled is False


# === Happy path ==========================================================


@pytest.mark.asyncio
async def test_approve_resolves_broker_with_allow_true() -> None:
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    req = _make_request()
    await registry.add(req)

    import asyncio

    async def wait_for_resolve():
        return await broker.wait(
            interaction_id=req.request_id,
            kind="permission",
            timeout_seconds=2.0,
        )

    waiter = asyncio.create_task(wait_for_resolve())
    # tiny yield so the waiter parks on broker.wait before resolve fires
    await asyncio.sleep(0)
    out = await try_handle_control_command(
        message=f"/approve {req.short_id}",
        session_id="s1", registry=registry, broker=broker,
    )
    response = await waiter

    assert out.handled is True
    assert out.allowed is True
    assert out.resolved_request_id == req.request_id
    assert isinstance(response, UserPromptResponse)
    assert response.allow is True


@pytest.mark.asyncio
async def test_deny_resolves_broker_with_allow_false() -> None:
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    req = _make_request()
    await registry.add(req)

    import asyncio
    waiter = asyncio.create_task(broker.wait(
        interaction_id=req.request_id, kind="permission", timeout_seconds=2.0,
    ))
    await asyncio.sleep(0)
    out = await try_handle_control_command(
        message=f"/deny {req.short_id}",
        session_id="s1", registry=registry, broker=broker,
    )
    response = await waiter

    assert out.handled is True
    assert out.allowed is False
    assert response.allow is False


@pytest.mark.asyncio
async def test_allow_alias_works() -> None:
    """``/allow`` is an alias for ``/approve``."""
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    req = _make_request()
    await registry.add(req)

    import asyncio
    waiter = asyncio.create_task(broker.wait(
        interaction_id=req.request_id, kind="permission", timeout_seconds=2.0,
    ))
    await asyncio.sleep(0)
    out = await try_handle_control_command(
        message=f"/allow {req.short_id}",
        session_id="s1", registry=registry, broker=broker,
    )
    await waiter
    assert out.handled is True
    assert out.allowed is True


@pytest.mark.asyncio
async def test_reject_alias_works() -> None:
    """``/reject`` is an alias for ``/deny``."""
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    req = _make_request()
    await registry.add(req)

    import asyncio
    waiter = asyncio.create_task(broker.wait(
        interaction_id=req.request_id, kind="permission", timeout_seconds=2.0,
    ))
    await asyncio.sleep(0)
    out = await try_handle_control_command(
        message=f"/reject {req.short_id}",
        session_id="s1", registry=registry, broker=broker,
    )
    await waiter
    assert out.handled is True
    assert out.allowed is False


@pytest.mark.asyncio
async def test_uppercase_verb_works() -> None:
    """Users may type ``/APPROVE`` — verb is case-insensitive."""
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    req = _make_request()
    await registry.add(req)

    import asyncio
    waiter = asyncio.create_task(broker.wait(
        interaction_id=req.request_id, kind="permission", timeout_seconds=2.0,
    ))
    await asyncio.sleep(0)
    out = await try_handle_control_command(
        message=f"/APPROVE {req.short_id.upper()}",
        session_id="s1", registry=registry, broker=broker,
    )
    await waiter
    assert out.handled is True


# === No match / wrong session / typos ====================================


@pytest.mark.asyncio
async def test_no_matching_request_returns_ack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Typo / timed-out short_id → handled=True with friendly ack;
    broker.resolve NOT called (no waiter to time out)."""
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    out = await try_handle_control_command(
        message="/approve nonexistent",
        session_id="s1", registry=registry, broker=broker,
    )
    assert out.handled is True
    assert out.resolved_request_id is None
    assert out.ack_message and "找不到" in out.ack_message


@pytest.mark.asyncio
async def test_natural_language_approve_resolves_when_one_pending() -> None:
    """``同意`` with one pending → resolves with allow=True (no
    short_id needed when context is unambiguous)."""
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    req = _make_request(session_id="s1")
    await registry.add(req)
    import asyncio
    waiter = asyncio.create_task(broker.wait(
        interaction_id=req.request_id, kind="permission", timeout_seconds=2.0,
    ))
    await asyncio.sleep(0)
    out = await try_handle_control_command(
        message="同意",
        session_id="s1", registry=registry, broker=broker,
    )
    response = await waiter
    assert out.handled is True
    assert out.allowed is True
    assert response.allow is True


@pytest.mark.asyncio
async def test_natural_language_deny_resolves_when_one_pending() -> None:
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    req = _make_request(session_id="s1")
    await registry.add(req)
    import asyncio
    waiter = asyncio.create_task(broker.wait(
        interaction_id=req.request_id, kind="permission", timeout_seconds=2.0,
    ))
    await asyncio.sleep(0)
    out = await try_handle_control_command(
        message="拒绝",
        session_id="s1", registry=registry, broker=broker,
    )
    await waiter
    assert out.handled is True
    assert out.allowed is False


@pytest.mark.asyncio
async def test_natural_language_no_pending_falls_through() -> None:
    """SAFETY: natural-language verbs without any pending request
    are normal chat, not control commands. Otherwise the bot would
    intercept innocent user replies like ``好的`` or ``ok``."""
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    for verb in ("好的", "ok", "yes", "同意", "拒绝", "no"):
        out = await try_handle_control_command(
            message=verb, session_id="s1",
            registry=registry, broker=broker,
        )
        assert out.handled is False, f"verb {verb!r} should pass through"


@pytest.mark.asyncio
async def test_slash_without_short_id_resolves_single_pending() -> None:
    """``/approve`` (no short_id) → resolves the single pending."""
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    req = _make_request(session_id="s1")
    await registry.add(req)
    import asyncio
    waiter = asyncio.create_task(broker.wait(
        interaction_id=req.request_id, kind="permission", timeout_seconds=2.0,
    ))
    await asyncio.sleep(0)
    out = await try_handle_control_command(
        message="/approve",
        session_id="s1", registry=registry, broker=broker,
    )
    await waiter
    assert out.handled is True
    assert out.allowed is True


@pytest.mark.asyncio
async def test_ambiguous_prompts_for_short_id() -> None:
    """Multiple pending + no short_id → handled=True with ack,
    broker NOT resolved (user must disambiguate)."""
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    req_a = _make_request(session_id="s1")
    req_b = _make_request(session_id="s1")
    await registry.add(req_a)
    await registry.add(req_b)
    out = await try_handle_control_command(
        message="同意",
        session_id="s1", registry=registry, broker=broker,
    )
    assert out.handled is True
    assert out.resolved_request_id is None
    assert out.ack_message and "多个" in out.ack_message


@pytest.mark.asyncio
async def test_cross_session_isolation() -> None:
    """Pending request in s1 isn't resolvable via /approve from s2.

    Returns handled=True with ack (since the short_id has no match
    in s2). The pending request in s1 stays pending — the registry's
    cross-session isolation enforces this."""
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    req = _make_request(session_id="s1")
    await registry.add(req)

    out = await try_handle_control_command(
        message=f"/approve {req.short_id}",
        session_id="s2",  # wrong session!
        registry=registry, broker=broker,
    )
    assert out.handled is True
    assert out.resolved_request_id is None  # broker NOT resolved
    # Confirm request is still pending in s1
    assert registry.get(req.request_id) is req
