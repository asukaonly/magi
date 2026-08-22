"""powershell tool must refuse destructive commands without confirm_destructive."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from magi.tools.builtin.powershell_tool import PowerShellTool
from magi.tools.schema import ToolExecutionContext


def _ctx(workspace: Path) -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="a", workspace=str(workspace), env_vars={})


@pytest.mark.asyncio
async def test_powershell_destructive_blocked_without_confirm(tmp_path: Path) -> None:
    res = await PowerShellTool().execute(
        {"command": "rm -rf foo"}, _ctx(tmp_path)
    )
    assert not res.success
    assert res.data["risk_level"] == "destructive"
    assert "confirm_destructive" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_powershell_remove_item_recurse_force_blocked(tmp_path: Path) -> None:
    res = await PowerShellTool().execute(
        {"command": "Remove-Item -Recurse -Force C:\\foo"}, _ctx(tmp_path)
    )
    assert not res.success
    assert res.data["risk_level"] == "destructive"


@pytest.mark.asyncio
async def test_powershell_alias_and_abbreviated_switches_blocked(
    tmp_path: Path,
) -> None:
    res = await PowerShellTool().execute(
        {"command": "ri C:\\* -r -fo"},
        _ctx(tmp_path),
    )

    assert not res.success
    assert res.error_code == "POLICY_BLOCKED"
    assert res.data["risk_level"] == "destructive"


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows path through classifier only")
@pytest.mark.asyncio
async def test_powershell_safe_command_passes_classifier(tmp_path: Path) -> None:
    res = await PowerShellTool().execute({"command": "echo hi"}, _ctx(tmp_path))
    assert res.error_code != "POLICY_BLOCKED"
    assert res.data is not None
    assert "risk_level" in res.data
