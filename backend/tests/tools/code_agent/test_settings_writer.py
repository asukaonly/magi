"""Tests for code_agent settings writers."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

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


def test_write_user_settings_deep_merges_existing(isolated_magi_home: Path, tmp_path: Path) -> None:
    user_path = write_user_settings(
        {
            "default_adapter": "claude_code",
            "claude_code": {"max_budget_usd": 12.5},
        }
    )
    write_user_settings({"claude_code": {"default_model": "opus"}})
    workspace = tmp_path / "ws"
    workspace.mkdir()
    s = load_settings(workspace_root=workspace)
    assert s.default_adapter == "claude_code"
    assert s.claude_code.max_budget_usd == 12.5
    assert s.claude_code.default_model == "opus"

    assert user_path == isolated_magi_home / "code_agent.toml"
    user_bytes = user_path.read_bytes()
    project_path = write_project_settings(workspace, {"default_adapter": "codex"})
    assert project_path == workspace / ".magi/code_agent.toml"
    project_settings = load_settings(workspace_root=workspace)
    assert project_settings.default_adapter == "codex"
    assert project_settings.claude_code == s.claude_code
    assert user_path.read_bytes() == user_bytes
    reset_project_settings(workspace)
    reset_project_settings(workspace)
    assert not project_path.exists()
    assert load_settings(workspace_root=workspace) == s
    assert user_path.read_bytes() == user_bytes


@pytest.mark.parametrize("patch", [
    {"default_adapter": "not-a-tool"}, {"constraints": {"default_timeout_s": 0}},
    {"constraints": {"default_timeout_s": 3601}}, {"constraints": {"default_timeout_s": 60.5}},
    {"enabled": None}, {"invented": True},
])
def test_invalid_user_patch_preserves_existing_file(isolated_magi_home: Path, patch: dict) -> None:
    target = write_user_settings({"default_adapter": "codex"})
    original = target.read_bytes()
    with pytest.raises(ValidationError):
        write_user_settings(patch)
    assert target.read_bytes() == original


def test_failed_atomic_replace_preserves_user_settings_and_cleans_staging(
    isolated_magi_home, monkeypatch
):
    target = write_user_settings({"default_adapter": "codex"})
    before = target.read_bytes()
    attempted = []

    def fail_replace(source, destination):
        assert Path(destination) == target
        assert target.read_bytes() == before
        staged = Path(source)
        assert staged != target
        assert staged.parent == target.parent
        assert 'default_adapter = "auto"' in staged.read_text()
        attempted.append(staged)
        raise OSError("injected atomic replacement failure")

    with monkeypatch.context() as patch:
        patch.setattr("magi_plugin_sdk.fs.os.replace", fail_replace)
        with pytest.raises(OSError, match="injected atomic replacement failure"):
            write_user_settings({"default_adapter": "auto"})
    assert len(attempted) == 1
    assert not attempted[0].exists()
    assert target.read_bytes() == before
    assert load_settings().default_adapter == "codex"
    write_user_settings({"default_adapter": "auto"})
    assert load_settings().default_adapter == "auto"
    assert list(target.parent.glob("*.tmp")) == []
