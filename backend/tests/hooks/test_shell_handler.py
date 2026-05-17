"""Unit tests for the shell-command HookHandler wrapper."""

from __future__ import annotations

import json

import pytest

from magi.hooks.contracts import HookContext, HookEventType, HookOutcome
from magi.hooks.shell_handler import build_shell_hook_handler


def _ctx() -> HookContext:
    return HookContext(
        event_type=HookEventType.PRE_TOOL_USE,
        tool_name="bash",
        arguments={"command": "echo hi"},
    )


@pytest.mark.asyncio
async def test_continue_on_exit_zero():
    handler = build_shell_hook_handler(command="exit 0", source="t1")
    assert (await handler(_ctx())).outcome == HookOutcome.CONTINUE


@pytest.mark.asyncio
async def test_deny_on_exit_two_with_stderr_reason():
    handler = build_shell_hook_handler(
        command="echo because-policy >&2; exit 2",
        source="t2",
    )
    decision = await handler(_ctx())
    assert decision.outcome == HookOutcome.DENY
    assert "because-policy" in (decision.reason or "")


@pytest.mark.asyncio
async def test_deny_via_json_payload():
    payload = json.dumps({"decision": "block", "reason": "json-block"})
    handler = build_shell_hook_handler(
        command=f"printf '%s' {payload!r}",
        source="t3",
    )
    decision = await handler(_ctx())
    assert decision.outcome == HookOutcome.DENY
    assert decision.reason == "json-block"


@pytest.mark.asyncio
async def test_modify_via_json_payload():
    payload = json.dumps({
        "decision": "modify",
        "modified_arguments": {"command": "echo masked"},
    })
    handler = build_shell_hook_handler(
        command=f"printf '%s' {payload!r}",
        source="t4",
    )
    decision = await handler(_ctx())
    assert decision.outcome == HookOutcome.MODIFY
    assert decision.modified_arguments == {"command": "echo masked"}


@pytest.mark.asyncio
async def test_timeout_degrades_to_continue():
    handler = build_shell_hook_handler(
        command="sleep 5",
        timeout_s=0.3,
        source="t5",
    )
    decision = await handler(_ctx())
    assert decision.outcome == HookOutcome.CONTINUE


@pytest.mark.asyncio
async def test_unknown_exit_code_logs_and_continues():
    handler = build_shell_hook_handler(command="exit 3", source="t6")
    decision = await handler(_ctx())
    assert decision.outcome == HookOutcome.CONTINUE
