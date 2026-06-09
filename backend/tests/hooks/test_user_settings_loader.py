"""Tests for ~/.claude/settings.json hook discovery."""

from __future__ import annotations

import json
import os

import pytest

from magi.hooks.user_settings import load_user_hook_handlers
from magi.hooks.registry import HookRegistry


@pytest.fixture
def settings_path(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setenv("MAGI_CLAUDE_SETTINGS_PATH", str(path))
    return path


@pytest.mark.asyncio
async def test_no_file_returns_zero(monkeypatch, tmp_path):
    monkeypatch.setenv("MAGI_CLAUDE_SETTINGS_PATH", str(tmp_path / "missing.json"))
    registry = HookRegistry()
    assert (await load_user_hook_handlers(registry)) == 0
    assert registry.total() == 0


@pytest.mark.asyncio
async def test_malformed_json_returns_zero(settings_path):
    settings_path.write_text("{not json")
    registry = HookRegistry()
    assert (await load_user_hook_handlers(registry)) == 0


@pytest.mark.asyncio
async def test_loads_multiple_hooks(settings_path):
    settings_path.write_text(json.dumps({
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": "exit 0"},
                        {"type": "command", "command": "exit 0"},
                    ],
                },
            ],
            "PostSkillUse": [
                {"hooks": [{"type": "command", "command": "exit 0"}]},
            ],
        },
    }))
    registry = HookRegistry()
    assert (await load_user_hook_handlers(registry)) == 3
    assert registry.total() == 3


@pytest.mark.asyncio
async def test_unknown_event_type_is_skipped(settings_path):
    settings_path.write_text(json.dumps({
        "hooks": {
            "TotallyMadeUp": [{"hooks": [{"type": "command", "command": "exit 0"}]}],
            "PreToolUse": [{"hooks": [{"type": "command", "command": "exit 0"}]}],
        },
    }))
    registry = HookRegistry()
    assert (await load_user_hook_handlers(registry)) == 1


@pytest.mark.asyncio
async def test_unsupported_spec_type_is_skipped(settings_path):
    settings_path.write_text(json.dumps({
        "hooks": {
            "PreToolUse": [
                {"hooks": [{"type": "python", "command": "raise"}]},
                {"hooks": [{"type": "command", "command": "exit 0"}]},
            ],
        },
    }))
    registry = HookRegistry()
    assert (await load_user_hook_handlers(registry)) == 1
