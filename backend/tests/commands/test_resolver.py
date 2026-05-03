"""Tests for the user-invocable resolver."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from magi.commands.resolver import UserInvocableResolver
from magi_plugin_sdk.tools import ToolSchema


def _fake_registry(tools: dict[str, dict]) -> MagicMock:
    registry = MagicMock()

    def get_tool(name: str):
        spec = tools.get(name)
        if spec is None:
            return None
        tool = MagicMock()
        tool.get_schema.return_value = ToolSchema(
            name=name,
            description="",
            category="test",
            metadata=spec.get("metadata") or {},
        )
        return tool

    registry.get_tool.side_effect = get_tool
    registry.list_tools.return_value = list(tools.keys())
    return registry


def test_metadata_user_invocable_true(tmp_path):
    resolver = UserInvocableResolver(whitelist_path=tmp_path / "missing.toml")
    registry = _fake_registry({"read_file": {"metadata": {"user_invocable": True}}})
    assert resolver.is_user_invocable(registry, "read_file") is True


def test_default_metadata_not_user_invocable(tmp_path):
    resolver = UserInvocableResolver(whitelist_path=tmp_path / "missing.toml")
    registry = _fake_registry({"bash": {"metadata": {}}})
    assert resolver.is_user_invocable(registry, "bash") is False


def test_toml_whitelist_grants_invocable(tmp_path):
    path = tmp_path / "user_invocable_tools.toml"
    path.write_text('allow = ["bash", "search_web"]\n')
    resolver = UserInvocableResolver(whitelist_path=path)
    registry = _fake_registry({"bash": {"metadata": {}}, "search_web": {"metadata": {}}})
    assert resolver.is_user_invocable(registry, "bash") is True
    assert resolver.is_user_invocable(registry, "search_web") is True


def test_unknown_tool_returns_false(tmp_path):
    resolver = UserInvocableResolver(whitelist_path=tmp_path / "missing.toml")
    registry = _fake_registry({})
    assert resolver.is_user_invocable(registry, "nope") is False


def test_list_user_invocable_combines_metadata_and_whitelist(tmp_path):
    path = tmp_path / "user_invocable_tools.toml"
    path.write_text('allow = ["bash"]\n')
    resolver = UserInvocableResolver(whitelist_path=path)
    registry = _fake_registry(
        {
            "bash": {"metadata": {}},
            "read_file": {"metadata": {"user_invocable": True}},
            "secret_op": {"metadata": {}},
        }
    )
    assert resolver.list_user_invocable(registry) == ["bash", "read_file"]


def test_whitelist_reloaded_when_mtime_changes(tmp_path):
    path = tmp_path / "user_invocable_tools.toml"
    path.write_text('allow = ["foo"]\n')
    resolver = UserInvocableResolver(whitelist_path=path)
    registry = _fake_registry({"foo": {"metadata": {}}, "bar": {"metadata": {}}})

    assert resolver.is_user_invocable(registry, "foo") is True
    assert resolver.is_user_invocable(registry, "bar") is False

    import os
    import time as _time

    _time.sleep(0.01)
    path.write_text('allow = ["bar"]\n')
    new_mtime = path.stat().st_mtime + 1
    os.utime(path, (new_mtime, new_mtime))

    assert resolver.is_user_invocable(registry, "bar") is True


def test_invalid_toml_logged_and_treated_as_empty(tmp_path):
    path = tmp_path / "user_invocable_tools.toml"
    path.write_text("not valid toml = {{{")
    resolver = UserInvocableResolver(whitelist_path=path)
    registry = _fake_registry({"foo": {"metadata": {}}})
    assert resolver.is_user_invocable(registry, "foo") is False
