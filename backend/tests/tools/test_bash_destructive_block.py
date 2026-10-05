"""bash tool must refuse destructive commands without confirm_destructive."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from magi.tools.builtin.bash_tool import BashTool
from magi.tools.schema import ToolExecutionContext


requires_posix_bash = pytest.mark.skipif(
    os.name == "nt",
    reason="Bash is a host-native tool only on POSIX",
)


def _ctx(workspace: Path) -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="a", workspace=str(workspace), env_vars={})


@pytest.mark.asyncio
async def test_destructive_blocked_without_confirm(tmp_path: Path) -> None:
    target = tmp_path / "victim"
    target.mkdir()
    (target / "f").write_text("x")
    res = await BashTool().execute({"command": f"rm -rf {target}"}, _ctx(tmp_path))
    assert not res.success
    assert (target / "f").exists(), "must not have run"
    assert res.data["risk_level"] == "destructive"
    assert "destructive" in (res.error or "").lower()
    assert "confirm_destructive" in (res.error or "").lower()


@pytest.mark.asyncio
@requires_posix_bash
async def test_destructive_allowed_with_confirm(tmp_path: Path) -> None:
    target = tmp_path / "victim"
    target.mkdir()
    (target / "f").write_text("x")
    res = await BashTool().execute(
        {"command": f"rm -rf {target}", "confirm_destructive": True},
        _ctx(tmp_path),
    )
    assert res.success, res.error
    assert not target.exists()
    assert res.data["risk_level"] == "destructive"


@pytest.mark.asyncio
@requires_posix_bash
async def test_read_only_includes_risk_level(tmp_path: Path) -> None:
    res = await BashTool().execute({"command": "echo hi"}, _ctx(tmp_path))
    assert res.success, res.error
    assert res.data["risk_level"] == "read_only"
    assert "hi" in res.data["stdout"]


@pytest.mark.asyncio
@requires_posix_bash
async def test_mutating_does_not_require_confirm(tmp_path: Path) -> None:
    res = await BashTool().execute({"command": f"echo hi > {tmp_path}/out.txt"}, _ctx(tmp_path))
    assert res.success, res.error
    assert res.data["risk_level"] == "mutating"

    assert (tmp_path / "out.txt").read_bytes() == b"hi\n"


@pytest.mark.asyncio
async def test_chained_destructive_command_never_runs_any_stage(tmp_path):
    import shlex

    victim = tmp_path / "foo"
    victim.mkdir()
    (victim / "content").write_bytes(b"keep this exact content")
    marker = tmp_path / "executed"
    command = f"cd {shlex.quote(str(tmp_path))} && echo started > executed && rm -rf foo"
    result = await BashTool().execute({"command": command}, _ctx(tmp_path))
    assert not result.success
    assert result.error_code == "POLICY_BLOCKED"
    assert result.data["risk_level"] == "destructive"
    assert not marker.exists()
    assert (victim / "content").read_bytes() == b"keep this exact content"
