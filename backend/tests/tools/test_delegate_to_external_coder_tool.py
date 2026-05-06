"""Integration tests for delegate_to_external_coder builtin tool."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from magi.tools.builtin.delegate_to_external_coder_tool import (
    DelegateToExternalCoderTool,
)
from magi.tools.schema import ToolExecutionContext


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "ci@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=path, check=True)
    (path / "README.md").write_text("# repo\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


def _ctx(workspace: Path, session_id: str | None = "s1") -> ToolExecutionContext:
    env_vars = {"session_id": session_id} if session_id else {}
    return ToolExecutionContext(agent_id="a", workspace=str(workspace), env_vars=env_vars)


@pytest.fixture
def isolated_magi_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "magi_home"
    home.mkdir()
    monkeypatch.setenv("MAGI_HOME", str(home))
    return home


@pytest.mark.asyncio
async def test_dry_run_returns_success_without_running_adapter(
    isolated_magi_home: Path, tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    res = await DelegateToExternalCoderTool().execute(
        {
            "prompt": "add max_retries to connect()",
            "files_hint": ["README.md"],
            "adapter": "claude_code",
            "timeout_s": 60,
            "dry_run": True,
        },
        _ctx(repo),
    )
    assert res.success, res.error
    assert res.data["success"] is True
    assert res.data["summary"] == "dry run"
    assert res.data["delegation_id"]


@pytest.mark.asyncio
async def test_no_session_id_rejected(isolated_magi_home: Path, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    res = await DelegateToExternalCoderTool().execute(
        {"prompt": "x", "dry_run": True},
        _ctx(repo, session_id=None),
    )
    assert not res.success
    assert "session" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_non_repo_workspace_rejected(isolated_magi_home: Path, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    res = await DelegateToExternalCoderTool().execute(
        {"prompt": "x", "dry_run": True},
        _ctx(plain),
    )
    assert not res.success
    assert "git" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_missing_prompt_rejected(isolated_magi_home: Path, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    res = await DelegateToExternalCoderTool().execute(
        {"prompt": "  ", "dry_run": True},
        _ctx(repo),
    )
    assert not res.success
    assert "prompt" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_invalid_adapter_rejected(isolated_magi_home: Path, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    res = await DelegateToExternalCoderTool().execute(
        {"prompt": "x", "adapter": "nope", "dry_run": True},
        _ctx(repo),
    )
    assert not res.success
    assert "adapter" in (res.error or "").lower()


def test_tool_registered() -> None:
    from magi.tools.builtin.delegate_to_external_coder_tool import (
        DelegateToExternalCoderTool as Canonical,
    )
    from magi.tools.builtin import DelegateToExternalCoderTool as FromBuiltin
    from magi.tools import DelegateToExternalCoderTool as FromTools
    from magi.tools.core_tools import CORE_TOOL_CLASSES
    assert FromBuiltin is Canonical
    assert FromTools is Canonical
    assert Canonical in CORE_TOOL_CLASSES


def test_tool_schema_advertises_modes() -> None:
    tool = DelegateToExternalCoderTool()
    enum_param = next(p for p in tool.schema.parameters if p.name == "adapter")
    assert "claude_code" in (enum_param.enum or [])
    assert "codex" in (enum_param.enum or [])
    assert "auto" in (enum_param.enum or [])
