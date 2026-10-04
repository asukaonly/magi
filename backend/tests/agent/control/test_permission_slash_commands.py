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


@pytest.mark.parametrize(
    "input_text",
    [
        pytest.param("please draw a cat", id="plain_chat_is_not_a_command"),
        pytest.param("yes /approve abc123 please", id="slash_inside_message_is_not_a_command"),
        pytest.param("/help", id="unknown_slash_command_is_not_handled"),
    ],
)
@pytest.mark.asyncio
async def test_unrecognized_message_is_not_a_permission_command(input_text) -> None:
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    out = await try_handle_control_command(
        message=input_text, session_id="s1", registry=registry, broker=broker
    )
    assert out.handled is False


# === Happy path ==========================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message,allowed",
    [
        ("/approve {token}", True),
        ("/deny {token}", False),
        ("/allow {token}", True),
        ("/reject {token}", False),
        ("/APPROVE AB12CD", True),
        ("/approve", True),
        ("同意", True),
        ("拒绝", False),
    ],
)
async def test_permission_command_resolves_actual_waiter(message, allowed):
    import asyncio

    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    req = _make_request()
    req.short_id = "ab12cd"
    await registry.add(req)
    waiter = asyncio.create_task(
        broker.wait(
            interaction_id=req.request_id,
            kind="permission",
            timeout_seconds=2.0,
        )
    )
    try:
        await asyncio.sleep(0)
        assert broker.pending_count() == 1
        out = await try_handle_control_command(
            message=message.format(token=req.short_id),
            session_id="s1",
            registry=registry,
            broker=broker,
        )
        response = await waiter
        assert out.handled is True
        assert out.allowed is allowed
        assert out.resolved_request_id == req.request_id
        assert isinstance(response, UserPromptResponse)
        assert response.allow is allowed
        assert broker.pending_count() == 0
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


# === No match / wrong session / typos ====================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,expected_ack",
    [
        ("missing", "找不到"),
        ("ambiguous", "多个"),
        ("wrong_session", "找不到"),
    ],
)
async def test_unmatched_permission_command_leaves_waiters_pending(scenario, expected_ack):
    import asyncio

    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    requests = [_make_request(session_id="s1") for _ in range(2 if scenario == "ambiguous" else 1)]
    waiters = []
    try:
        for req in requests:
            await registry.add(req)
            waiters.append(
                asyncio.create_task(
                    broker.wait(
                        interaction_id=req.request_id,
                        kind="permission",
                        timeout_seconds=2.0,
                    )
                )
            )
        await asyncio.sleep(0)
        assert broker.pending_count() == len(requests)
        pending = broker.list_pending()
        message = (
            "同意"
            if scenario == "ambiguous"
            else (
                "/approve nonexistent"
                if scenario == "missing"
                else f"/approve {requests[0].short_id}"
            )
        )
        out = await try_handle_control_command(
            message=message,
            session_id="s2" if scenario == "wrong_session" else "s1",
            registry=registry,
            broker=broker,
        )
        assert out.handled is True
        assert out.resolved_request_id is None
        assert expected_ack in out.ack_message
        assert all(not item.future.done() for item in pending)

        # A valid response still resolves each original request after the rejected attempt.
        for req, waiter in zip(requests, waiters):
            accepted = await try_handle_control_command(
                message=f"/approve {req.short_id}",
                session_id="s1",
                registry=registry,
                broker=broker,
            )
            assert accepted.resolved_request_id == req.request_id
            assert (await waiter).allow is True
        assert broker.pending_count() == 0
    finally:
        for waiter in waiters:
            waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)


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
