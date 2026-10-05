"""Tests for ~/.claude/settings.json hook discovery."""

from __future__ import annotations

import json

import pytest

from magi.hooks.user_settings import load_user_hook_handlers
from magi.hooks.registry import HookRegistry


@pytest.fixture
def settings_path(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setenv("MAGI_CLAUDE_SETTINGS_PATH", str(path))
    return path


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [None, "{not json", "[]", '{"hooks":null}'])
async def test_unavailable_settings_leave_registry_unchanged(settings_path, content):
    from magi.hooks import HookContext, HookDecision, HookEventType, HookGateway

    registry = HookRegistry()

    async def existing(ctx):
        return HookDecision.deny("existing policy")

    registry.register(HookEventType.PRE_TOOL_USE, existing)
    if content is not None:
        settings_path.write_text(content)
    assert await load_user_hook_handlers(registry) == 0
    assert registry.total() == 1
    decision = await HookGateway(registry).dispatch(
        HookContext(event_type=HookEventType.PRE_TOOL_USE)
    )
    assert decision.reason == "existing policy"


@pytest.mark.asyncio
async def test_loaded_hooks_preserve_event_matcher_and_command(settings_path, tmp_path):
    import shlex
    from magi.hooks import HookContext, HookEventType, HookGateway, HookOutcome

    calls = tmp_path / "calls.txt"

    def spec(label, kind="command"):
        return {
            "type": kind,
            "command": f"printf '%s\n' {shlex.quote(label)} >> {shlex.quote(str(calls))}",
        }

    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [spec("pre-a"), spec("pre-b"), spec("unsupported", "python")],
                        }
                    ],
                    "PostSkillUse": [{"hooks": [spec("post-skill")]}],
                    "TotallyMadeUp": [{"hooks": [spec("unknown-event")]}],
                }
            }
        )
    )
    registry = HookRegistry()
    assert await load_user_hook_handlers(registry) == 3
    assert registry.total() == 3
    gateway = HookGateway(registry)
    for event, matcher, expected in [
        (HookEventType.PRE_TOOL_USE, "Other", []),
        (HookEventType.PRE_TOOL_USE, "Bash", ["pre-a", "pre-b"]),
        (HookEventType.POST_SKILL_USE, None, ["pre-a", "pre-b", "post-skill"]),
        (HookEventType.POST_TOOL_USE, "Bash", ["pre-a", "pre-b", "post-skill"]),
    ]:
        decision = await gateway.dispatch(HookContext(event_type=event, matcher_key=matcher))
        assert decision.outcome == HookOutcome.CONTINUE
        assert (calls.read_text().splitlines() if calls.exists() else []) == expected
