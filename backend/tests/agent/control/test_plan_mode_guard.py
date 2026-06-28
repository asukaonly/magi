"""Gateway plan-mode guard integration."""

from __future__ import annotations

import pytest

from magi.control.common import InteractionBroker
from magi.control.permission.classifier import RiskClassifier
from magi.control.permission.contracts import (
    PermissionOutcome,
    ToolOrigin,
)
from magi.control.permission.gateway import PermissionGateway
from magi.control.permission.rules import PermissionRuleStore
from magi.control.session_store import ControlSessionStore
from magi.control.settings import ControlSettings, PermissionMode


async def _gateway_with_store() -> tuple[PermissionGateway, ControlSessionStore, PermissionRuleStore]:
    store = ControlSessionStore()
    rules = PermissionRuleStore(db_path=None)
    await rules.initialize()
    settings = ControlSettings(permission_mode=PermissionMode.OFF)
    gateway = PermissionGateway(
        classifier=RiskClassifier(),
        rules=rules,
        broker=InteractionBroker(),
        settings_provider=lambda: settings,
        session_override_provider=lambda _sid: None,
        prompter=None,
        prompt_timeout_seconds=5.0,
        plan_mode_guard=store.plan_allows,
    )
    return gateway, store, rules


@pytest.mark.asyncio
async def test_plan_mode_blocks_write_tool_even_in_off_mode() -> None:
    gateway, store, _ = await _gateway_with_store()
    await store.enter_plan_mode("s1")

    decision = await gateway.gate(
        tool_name="bash",
        tool_is_dangerous=True,
        arguments={"command": "echo hi"},
        agent_id="chat",
        session_id="s1",
        origin=ToolOrigin.CHAT,
    )
    assert decision.outcome is PermissionOutcome.DENIED
    assert decision.source == "plan_mode"
    assert "plan mode" in (decision.reason or "")


@pytest.mark.asyncio
async def test_plan_mode_allows_read_tool() -> None:
    gateway, store, _ = await _gateway_with_store()
    await store.enter_plan_mode("s1")

    decision = await gateway.gate(
        tool_name="file_read",
        tool_is_dangerous=False,
        arguments={"path": "/tmp/x"},
        agent_id="chat",
        session_id="s1",
        origin=ToolOrigin.CHAT,
    )
    assert decision.outcome is PermissionOutcome.ALLOWED


@pytest.mark.asyncio
async def test_plan_mode_inactive_lets_everything_through() -> None:
    gateway, _, _ = await _gateway_with_store()

    decision = await gateway.gate(
        tool_name="bash",
        tool_is_dangerous=True,
        arguments={"command": "ls"},
        agent_id="chat",
        session_id="s1",
        origin=ToolOrigin.CHAT,
    )
    # OFF mode + no plan mode → allowed.
    assert decision.outcome is PermissionOutcome.ALLOWED


@pytest.mark.asyncio
async def test_kill_list_beats_plan_mode() -> None:
    """Kill-list must remain the outermost check."""
    gateway, store, _ = await _gateway_with_store()
    await store.enter_plan_mode("s1")

    decision = await gateway.gate(
        tool_name="bash",
        tool_is_dangerous=True,
        arguments={"command": "rm -rf /"},
        agent_id="chat",
        session_id="s1",
        origin=ToolOrigin.CHAT,
    )
    assert decision.outcome is PermissionOutcome.KILL_LISTED
