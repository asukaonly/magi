"""powershell tool must refuse destructive commands without confirm_destructive."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.builtin.powershell_tool import PowerShellTool
from magi.tools.schema import ToolExecutionContext


def _ctx(workspace: Path) -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="a", workspace=str(workspace), env_vars={})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command", ["rm -rf foo", "Remove-Item -Recurse -Force C:\\foo", "ri C:\\* -r -fo"]
)
async def test_powershell_destructive_forms_stop_before_runner(tmp_path, monkeypatch, command):
    from unittest.mock import AsyncMock, Mock

    select = Mock(return_value="fake-powershell")
    run = AsyncMock()
    monkeypatch.setattr(PowerShellTool, "_select_executable", select)
    monkeypatch.setattr(PowerShellTool, "_run_powershell", run)
    result = await PowerShellTool().execute({"command": command}, _ctx(tmp_path))
    assert not result.success
    assert result.error_code == "POLICY_BLOCKED"
    assert result.data["risk_level"] == "destructive"
    assert "confirm_destructive" in result.error
    select.assert_not_called()
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_safe_powershell_command_reaches_executable_resolution(tmp_path, monkeypatch):
    from unittest.mock import Mock

    select = Mock(return_value=None)
    monkeypatch.setattr(PowerShellTool, "_select_executable", select)
    result = await PowerShellTool().execute({"command": "echo hi"}, _ctx(tmp_path))
    assert not result.success
    assert result.error_code == "UNSUPPORTED"
    assert result.data["risk_level"] == "read_only"
    select.assert_called_once_with(True)
