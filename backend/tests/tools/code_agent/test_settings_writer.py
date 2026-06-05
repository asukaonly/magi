"""Tests for code_agent settings writers."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.code_agent.settings import load_settings
from magi.tools.code_agent.settings_writer import (
    reset_project_settings,
    write_project_settings,
    write_user_settings,
)


@pytest.fixture
def isolated_magi_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "magi_home"
    home.mkdir()
    monkeypatch.setenv("MAGI_HOME", str(home))
    return home


def test_write_user_settings_creates_file(isolated_magi_home: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    write_user_settings({"default_adapter": "codex"})
    s = load_settings(workspace_root=workspace)
    assert s.default_adapter == "codex"


def test_write_user_settings_deep_merges_existing(isolated_magi_home: Path, tmp_path: Path) -> None:
    write_user_settings({
        "default_adapter": "claude_code",
        "claude_code": {"max_budget_usd": 12.5},
    })
    write_user_settings({"claude_code": {"default_model": "opus"}})
    workspace = tmp_path / "ws"
    workspace.mkdir()
    s = load_settings(workspace_root=workspace)
    assert s.default_adapter == "claude_code"
    assert s.claude_code.max_budget_usd == 12.5
    assert s.claude_code.default_model == "opus"


def test_write_user_settings_unknown_adapter_falls_back_via_loader(
    isolated_magi_home: Path,
) -> None:
    write_user_settings({"default_adapter": "not-a-tool"})
    workspace = isolated_magi_home / "ws"
    workspace.mkdir()
    s = load_settings(workspace_root=workspace)
    assert s.default_adapter == "auto"


def test_write_project_settings_lives_under_workspace_magi(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    write_project_settings(workspace, {"default_adapter": "codex"})
    project_toml = workspace / ".magi" / "code_agent.toml"
    assert project_toml.is_file()
    body = project_toml.read_text()
    assert "codex" in body
    s = load_settings(workspace_root=workspace)
    assert s.default_adapter == "codex"


def test_write_project_settings_overrides_user(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    write_user_settings({"default_adapter": "claude_code"})
    write_project_settings(workspace, {"default_adapter": "codex"})
    s = load_settings(workspace_root=workspace)
    assert s.default_adapter == "codex"


def test_reset_project_settings_removes_file(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    write_project_settings(workspace, {"default_adapter": "codex"})
    project_toml = workspace / ".magi" / "code_agent.toml"
    assert project_toml.is_file()
    reset_project_settings(workspace)
    assert not project_toml.is_file()


def test_reset_project_settings_when_missing_is_noop(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    reset_project_settings(workspace)


def test_writes_atomic_no_temp_files_on_success(
    isolated_magi_home: Path,
) -> None:
    write_user_settings({"default_adapter": "codex"})
    leftovers = [p for p in isolated_magi_home.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []
