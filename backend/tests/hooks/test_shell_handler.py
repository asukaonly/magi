"""Unit tests for the shell-command HookHandler wrapper."""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import sys

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
@pytest.mark.parametrize(
    "payload,exit_code,stderr,outcome,reason,arguments",
    [
        ("", 0, "", HookOutcome.CONTINUE, None, None),
        ("", 2, "because-policy", HookOutcome.DENY, "because-policy", None),
        (
            json.dumps({"decision": "block", "reason": "json-block"}),
            0,
            "",
            HookOutcome.DENY,
            "json-block",
            None,
        ),
        (
            json.dumps({"decision": "modify", "modified_arguments": {"command": "echo masked"}}),
            0,
            "",
            HookOutcome.MODIFY,
            None,
            {"command": "echo masked"},
        ),
    ],
)
async def test_shell_exit_and_json_protocol(payload, exit_code, stderr, outcome, reason, arguments):
    command = f"printf '%s' {shlex.quote(payload)}; printf '%s' {shlex.quote(stderr)} >&2; exit {exit_code}"
    decision = await build_shell_hook_handler(command=command, source="protocol")(_ctx())
    assert decision.outcome == outcome
    assert decision.source == "protocol"
    assert decision.reason == reason
    assert decision.modified_arguments == arguments


@pytest.mark.asyncio
async def test_timeout_terminates_and_reaps_child(monkeypatch, caplog):
    original = asyncio.create_subprocess_shell
    children = []

    async def spawn(*args, **kwargs):
        child = await original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_shell", spawn)
    command = f"exec {shlex.quote(sys.executable)} -c 'import time; time.sleep(60)'"
    handler = build_shell_hook_handler(command=command, timeout_s=0.1, source="deadline")
    try:
        with caplog.at_level(logging.WARNING, logger="magi.hooks.shell_handler"):
            decision = await asyncio.wait_for(handler(_ctx()), timeout=3)
        assert decision.outcome == HookOutcome.CONTINUE
        assert len(children) == 1
        assert children[0].returncode is not None and children[0].returncode < 0
        assert any("timed out" in r.message and "deadline" in r.message for r in caplog.records)
    finally:
        for child in children:
            if child.returncode is None:
                child.kill()
                await child.wait()


@pytest.mark.asyncio
async def test_unknown_exit_code_logs_and_continues(caplog, monkeypatch):
    monkeypatch.setattr("magi.hooks.shell_handler.full_content_logging_enabled", lambda: False)
    handler = build_shell_hook_handler(
        command="printf secret-stderr >&2; exit 3", source="unknown-exit"
    )
    with caplog.at_level(logging.WARNING, logger="magi.hooks.shell_handler"):
        decision = await handler(_ctx())
    assert decision.outcome == HookOutcome.CONTINUE
    warnings = [
        r.message
        for r in caplog.records
        if r.name == "magi.hooks.shell_handler" and r.levelno == logging.WARNING
    ]
    assert warnings == [
        "shell hook exited with unexpected code=3 source=unknown-exit stderr_chars=13"
    ]
    assert "secret-stderr" not in caplog.text
