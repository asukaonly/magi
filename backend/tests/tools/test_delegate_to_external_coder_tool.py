"""Integration tests for delegate_to_external_coder builtin tool."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from magi_plugin_sdk.capabilities import ToolCapabilities

from magi.tools.builtin import delegate_to_external_coder_tool as module
from magi.tools.builtin.delegate_to_external_coder_tool import (
    DelegateToExternalCoderTool,
    _binary_paths_from_settings,
    _resolve_adapter,
)
from magi.tools.code_agent.contracts import ProbeResult
from magi.tools.code_agent.settings import CodeAgentSettings
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


class _NoopArtifactRegistry:
    async def register(self, **_kwargs) -> None:
        return None


def _ctx(
    workspace: Path,
    session_id: str | None = "s1",
    *,
    with_artifact_registry: bool = True,
) -> ToolExecutionContext:
    env_vars = (
        {"session_id": session_id, "turn_id": "turn-1"}
        if session_id
        else {}
    )
    capabilities = (
        ToolCapabilities(delegation_artifacts=_NoopArtifactRegistry())
        if with_artifact_registry
        else None
    )
    return ToolExecutionContext(
        agent_id="a",
        workspace=str(workspace),
        env_vars=env_vars,
        capabilities=capabilities,
    )


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
    assert res.data["assistant_payload"] == {
        "code_agent_delegations": [
            {
                "delegation_id": res.data["delegation_id"],
                "turn_id": "turn-1",
                "workspace_path": str(repo.resolve()),
            }
        ],
    }


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
async def test_missing_artifact_registry_rejected_before_workspace_write(
    isolated_magi_home: Path,
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")

    res = await DelegateToExternalCoderTool().execute(
        {"prompt": "x", "dry_run": True},
        _ctx(repo, with_artifact_registry=False),
    )

    assert not res.success
    assert "registry" in (res.error or "").lower()
    assert not (repo / ".magi").exists()


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
    assert "assistant_payload" not in res.data


@pytest.mark.asyncio
async def test_symlink_workspace_rejected_without_writing_target(
    isolated_magi_home: Path,
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    alias = tmp_path / "repo-alias"
    alias.symlink_to(repo, target_is_directory=True)

    res = await DelegateToExternalCoderTool().execute(
        {"prompt": "x", "dry_run": True},
        _ctx(alias),
    )

    assert not res.success
    assert "symbolic link" in (res.error or "").lower()
    assert not (repo / ".magi").exists()


@pytest.mark.asyncio
async def test_unsafe_session_id_rejected_without_writing(
    isolated_magi_home: Path,
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path / "repo")

    res = await DelegateToExternalCoderTool().execute(
        {"prompt": "x", "dry_run": True},
        _ctx(repo, session_id="../outside"),
    )

    assert not res.success
    assert "session_id" in (res.error or "")
    assert not (repo / ".magi").exists()


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


def test_auto_default_adapter_picks_first_available_binary() -> None:
    settings = CodeAgentSettings(default_adapter="auto")
    resolved = _resolve_adapter(
        "auto",
        settings,
        {"claude_code": None, "codex": "/usr/local/bin/codex"},
    )
    assert resolved == "codex"


def test_configured_binary_path_overrides_detected_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        module,
        "probe_all",
        lambda force=False: {
            "claude_code": ProbeResult(
                name="claude_code",
                installed=True,
                binary_path="/detected/claude",
                version="1.0.0",
                detected_at=1,
                error=None,
                extras={},
            ),
            "codex": ProbeResult(
                name="codex",
                installed=True,
                binary_path="/detected/codex",
                version="1.0.0",
                detected_at=1,
                error=None,
                extras={},
            ),
        },
    )

    paths = _binary_paths_from_settings(
        CodeAgentSettings(claude_code={"binary_path": "/custom/claude"})
    )

    assert paths["claude_code"] == "/custom/claude"
    assert paths["codex"] == "/detected/codex"


@pytest.mark.asyncio
async def test_disabled_code_agent_setting_rejects_delegation(
    isolated_magi_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_repo(tmp_path / "repo")
    monkeypatch.setattr(
        module,
        "load_settings",
        lambda workspace_root: CodeAgentSettings(enabled=False),
    )

    res = await DelegateToExternalCoderTool().execute(
        {"prompt": "x", "dry_run": True},
        _ctx(repo),
    )

    assert not res.success
    assert "disabled" in (res.error or "").lower()
