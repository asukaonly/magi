"""Tests for the PowerShell tool.

The execution path requires a PowerShell host. When neither ``pwsh`` nor
``powershell`` is on PATH the tool should return a clean UNSUPPORTED
result; when one is available we verify the UTF-8 prelude really is
applied by round-tripping a CJK string back through stdout.
"""
from __future__ import annotations

import shutil

import pytest

from magi.tools.builtin.powershell_tool import PowerShellTool
from magi.tools.schema import ToolExecutionContext


def _context(workspace: str = ".") -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent", workspace=workspace)


def _powershell_available() -> bool:
    return any(shutil.which(name) for name in ("pwsh", "powershell"))


@pytest.mark.asyncio
async def test_powershell_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "magi.tools.builtin.powershell_tool.shutil.which",
        lambda _name: None,
    )
    monkeypatch.setattr(
        "magi.tools.builtin.powershell_tool._resolve_powershell_executable",
        lambda: None,
    )

    tool = PowerShellTool()
    result = await tool.execute({"command": "Write-Output hi"}, _context())

    assert result.success is False
    assert result.error_code == "UNSUPPORTED"


@pytest.mark.asyncio
@pytest.mark.skipif(not _powershell_available(), reason="No PowerShell host available")
async def test_powershell_runs_command_with_utf8_output() -> None:
    tool = PowerShellTool()
    result = await tool.execute(
        {"command": "Write-Output '测试-OK'", "timeout": 30},
        _context(),
    )

    assert result.success is True, result.error
    assert "测试-OK" in result.data["stdout"]
    assert result.data["return_code"] == 0
    assert "stdout_encoding" in result.data
