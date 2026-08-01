"""Tests for :class:`BrokeredPermissionPrompter` and :class:`PendingPermissionRegistry`."""

from __future__ import annotations

import asyncio

import pytest

from magi.control.common.interaction_broker import (
    InteractionBroker,
    InteractionTimeoutError,
)
from magi.control.permission.brokered_prompter import (
    BrokeredPermissionPrompter,
    PendingPermissionClearedError,
    PendingPermissionRegistry,
)
from magi.control.permission.contracts import (
    PermissionRequest,
    PermissionScope,
    RiskLevel,
    ToolOrigin,
)
from magi.control.permission.gateway import UserPromptResponse


def _request(request_id: str = "req-1", session_id: str | None = "sid-1") -> PermissionRequest:
    return PermissionRequest(
        request_id=request_id,
        tool_name="bash",
        arguments={"command": "rm file"},
        risk_level=RiskLevel.HIGH,
        origin=ToolOrigin.CHAT,
        agent_id="chat",
        session_id=session_id,
        turn_id=None,
        workspace=None,
    )


def test_permission_request_payload_uses_canonical_turn_id() -> None:
    req = _request()
    req.turn_id = "turn-1"
    req.timeout_seconds = 120.0
    req.expires_at = req.created_at + 120.0

    payload = req.to_dict()

    assert payload["turn_id"] == "turn-1"
    assert "task_id" not in payload
    assert payload["created_at_ms"] == int(req.created_at * 1000)
    assert payload["timeout_seconds"] == 120.0
    assert payload["expires_at_ms"] == int(req.expires_at * 1000)


@pytest.mark.asyncio
async def test_registry_round_trip() -> None:
    registry = PendingPermissionRegistry()
    req = _request("req-a", session_id="s1")
    await registry.add(req)
    assert registry.snapshot(session_id="s1") == [req]
    assert registry.snapshot(session_id="other") == []
    assert registry.snapshot(session_id="*") == [req]
    assert registry.get("req-a") is req
    assert await registry.remove("req-a") is req
    assert registry.snapshot(session_id="*") == []
    assert await registry.remove("req-a") is None


@pytest.mark.asyncio
async def test_registry_clear_rejects_adds_and_preserves_new_same_id() -> None:
    registry = PendingPermissionRegistry()
    old = _request("same-id")
    await registry.add(old)

    async with registry.user_content_clear_boundary():
        assert registry.snapshot(session_id="*") == []
        assert registry.get("same-id") is None
        with pytest.raises(PendingPermissionClearedError):
            await registry.add(_request("during-clear"))

    fresh = _request("same-id")
    await registry.add(fresh)
    assert await registry.remove("same-id", expected=old) is None
    assert registry.get("same-id") is fresh


@pytest.mark.asyncio
async def test_prompter_records_then_resolves_via_broker() -> None:
    broker = InteractionBroker()
    registry = PendingPermissionRegistry()
    prompter = BrokeredPermissionPrompter(broker=broker, registry=registry)
    req = _request("req-b", session_id="s1")

    async def resolver() -> None:
        # Wait until the registry sees it, then respond.
        for _ in range(50):
            if registry.get("req-b") is not None:
                break
            await asyncio.sleep(0.01)
        assert registry.get("req-b") is req
        await broker.resolve(
            interaction_id="req-b",
            kind="permission",
            response={
                "outcome": "allowed",
                "scope": PermissionScope.SESSION.value,
                "pattern": "rm *",
                "reason": "user approved",
            },
        )

    asyncio.create_task(resolver())
    response = await prompter(req, timeout_seconds=2.0)

    assert isinstance(response, UserPromptResponse)
    assert response.allow is True
    assert response.scope is PermissionScope.SESSION
    assert response.matcher == {"pattern": "rm *"}
    assert response.note == "user approved"
    # Registry cleared after resolution.
    assert registry.get("req-b") is None


@pytest.mark.asyncio
async def test_prompter_timeout_clears_registry() -> None:
    broker = InteractionBroker()
    registry = PendingPermissionRegistry()
    prompter = BrokeredPermissionPrompter(broker=broker, registry=registry)
    req = _request("req-c")

    with pytest.raises(InteractionTimeoutError):
        await prompter(req, timeout_seconds=0.05)

    assert registry.get("req-c") is None


@pytest.mark.asyncio
async def test_prompter_deny_defaults_scope() -> None:
    broker = InteractionBroker()
    registry = PendingPermissionRegistry()
    prompter = BrokeredPermissionPrompter(broker=broker, registry=registry)
    req = _request("req-d")

    async def resolver() -> None:
        for _ in range(50):
            if registry.get("req-d") is not None:
                break
            await asyncio.sleep(0.01)
        await broker.resolve(
            interaction_id="req-d",
            kind="permission",
            response={"outcome": "denied"},
        )

    asyncio.create_task(resolver())
    response = await prompter(req, timeout_seconds=2.0)
    assert response.allow is False
    assert response.scope is PermissionScope.ONE_SHOT
    assert response.matcher is None
    assert response.note is None


@pytest.mark.asyncio
async def test_prompter_invokes_notify_callback() -> None:
    broker = InteractionBroker()
    registry = PendingPermissionRegistry()
    seen: list[tuple[str, dict]] = []

    async def notify(event: str, payload: dict) -> None:
        seen.append((event, payload))

    prompter = BrokeredPermissionPrompter(
        broker=broker,
        registry=registry,
        notify_callback=notify,
    )
    req = _request("req-e")

    async def resolver() -> None:
        for _ in range(50):
            if registry.get("req-e") is not None:
                break
            await asyncio.sleep(0.01)
        await broker.resolve(
            interaction_id="req-e",
            kind="permission",
            response={"outcome": "allowed"},
        )

    asyncio.create_task(resolver())
    await prompter(req, timeout_seconds=2.0)

    # Phase H+2: notify fires on both ``requested`` and
    # ``resolved`` — see brokered_prompter.py finally block.
    assert len(seen) == 2
    event, payload = seen[0]
    assert event == "control.permission.requested"
    assert payload["request_id"] == "req-e"
    assert payload["tool_name"] == "bash"
    assert payload["timeout_seconds"] == 2.0
    assert payload["expires_at_ms"] == int((req.created_at + 2.0) * 1000)
    resolved_event, resolved_payload = seen[1]
    assert resolved_event == "control.permission.resolved"
    assert resolved_payload["request_id"] == "req-e"
