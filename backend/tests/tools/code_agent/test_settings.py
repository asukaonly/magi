"""Tests for code_agent settings loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.code_agent.settings import (
    CodeAgentSettings,
    load_settings,
)


@pytest.fixture
def isolated_magi_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MAGI_HOME", str(tmp_path))
    return tmp_path


def test_defaults_when_no_files(isolated_magi_home: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    s = load_settings(workspace_root=workspace)
    assert isinstance(s, CodeAgentSettings)
    assert s.enabled is True
    assert s.default_adapter == "auto"
    assert s.constraints.forbid_git_commit is True
    assert s.constraints.default_timeout_s >= 60
    assert s.claude_code.binary_path == ""
    assert s.codex.sandbox == "workspace-write"


def test_user_only_overrides_defaults(isolated_magi_home: Path, tmp_path: Path) -> None:
    (isolated_magi_home / "code_agent.toml").write_text(
        "default_adapter = \"codex\"\n"
        "[codex]\nbinary_path = \"/opt/codex/bin/codex\"\n"
        "[constraints]\ndefault_timeout_s = 120\n"
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    s = load_settings(workspace_root=workspace)
    assert s.default_adapter == "codex"
    assert s.codex.binary_path == "/opt/codex/bin/codex"
    assert s.constraints.default_timeout_s == 120


def test_auto_default_adapter_is_allowed(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    (isolated_magi_home / "code_agent.toml").write_text(
        "default_adapter = \"auto\"\n"
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    s = load_settings(workspace_root=workspace)
    assert s.default_adapter == "auto"


def test_project_overrides_user(isolated_magi_home: Path, tmp_path: Path) -> None:
    (isolated_magi_home / "code_agent.toml").write_text(
        "default_adapter = \"claude_code\"\n"
    )
    workspace = tmp_path / "ws"
    (workspace / ".magi").mkdir(parents=True)
    (workspace / ".magi" / "code_agent.toml").write_text(
        "default_adapter = \"codex\"\n"
        "[codex]\ndefault_model = \"o4\"\n"
    )
    s = load_settings(workspace_root=workspace)
    assert s.default_adapter == "codex"
    assert s.codex.default_model == "o4"


def test_invalid_toml_raises(isolated_magi_home: Path, tmp_path: Path) -> None:
    (isolated_magi_home / "code_agent.toml").write_text("[unclosed\n")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(Exception):
        load_settings(workspace_root=workspace)


def test_unknown_adapter_in_default_adapter_falls_back_to_auto(
    isolated_magi_home: Path, tmp_path: Path
) -> None:
    (isolated_magi_home / "code_agent.toml").write_text(
        "default_adapter = \"some-unknown\"\n"
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    s = load_settings(workspace_root=workspace)
    assert s.default_adapter == "auto"


def test_constraints_paths_are_lists(isolated_magi_home: Path, tmp_path: Path) -> None:
    (isolated_magi_home / "code_agent.toml").write_text(
        "[constraints]\nforbid_paths = [\".env\", \"id_rsa*\"]\n"
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    s = load_settings(workspace_root=workspace)
    assert ".env" in s.constraints.forbid_paths
    assert "id_rsa*" in s.constraints.forbid_paths
