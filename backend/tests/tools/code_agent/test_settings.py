"""Tests for code_agent settings loader."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

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


@pytest.mark.parametrize("adapter", ["auto", "claude_code", "codex"])
def test_user_file_decodes_adapter_and_constraint_overrides(isolated_magi_home, tmp_path, adapter):
    (isolated_magi_home / "code_agent.toml").write_text(
        f'default_adapter = "{adapter}"\n'
        '[codex]\nbinary_path = "/opt/codex/bin/codex"\n'
        '[constraints]\ndefault_timeout_s = 120\nforbid_paths = [".env", "id_rsa*"]\n'
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    s = load_settings(workspace_root=workspace)
    assert s.default_adapter == adapter
    assert s.codex.binary_path == "/opt/codex/bin/codex"
    assert s.constraints.default_timeout_s == 120

    assert s.constraints.forbid_paths == [".env", "id_rsa*"]


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


def test_invalid_toml_is_a_parser_error_and_valid_replacement_loads(isolated_magi_home, tmp_path):
    import sys

    if sys.version_info >= (3, 11):
        from tomllib import TOMLDecodeError
    else:
        from tomli import TOMLDecodeError
    target = isolated_magi_home / "code_agent.toml"
    target.write_text("[unclosed\n")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(TOMLDecodeError):
        load_settings(workspace_root=workspace)
    target.write_text('default_adapter = "auto"\n')
    assert load_settings(workspace_root=workspace).default_adapter == "auto"


def test_unknown_adapter_is_reported(
    isolated_magi_home: Path, tmp_path: Path
) -> None:
    (isolated_magi_home / "code_agent.toml").write_text(
        "default_adapter = \"some-unknown\"\n"
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(ValidationError):
        load_settings(workspace_root=workspace)
