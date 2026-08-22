"""Tests for the PowerShell tool.

The execution path requires a PowerShell host. When neither ``pwsh`` nor
``powershell`` is on PATH the tool should return a clean UNSUPPORTED
result; when one is available we verify the UTF-8 prelude really is
applied by round-tripping a CJK string back through stdout.
"""

from __future__ import annotations

import ntpath
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi_plugin_sdk.subprocess import BoundedStreamOutput, BoundedSubprocessResult
from magi.tools.builtin.powershell_tool import (
    MAX_POWERSHELL_COMMAND_TIMEOUT_SECONDS,
    POWERSHELL_TOOL_TIMEOUT_SECONDS,
    PowerShellTool,
    _well_known_windows_powershell_executable,
)
from magi.tools.builtin.bash_tool import SHELL_TOOL_TIMEOUT_HEADROOM_SECONDS
from magi.tools.schema import ToolExecutionContext


def _context(workspace: str = ".") -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent", workspace=workspace)


def _powershell_available() -> bool:
    return any(shutil.which(name) for name in ("pwsh", "powershell"))


def test_powershell_schema_leaves_outer_cleanup_headroom() -> None:
    tool = PowerShellTool()
    timeout_parameter = next(item for item in tool.schema.parameters if item.name == "timeout")

    assert timeout_parameter.max_value == MAX_POWERSHELL_COMMAND_TIMEOUT_SECONDS
    assert tool.schema.timeout == POWERSHELL_TOOL_TIMEOUT_SECONDS
    assert tool.schema.timeout == timeout_parameter.max_value + SHELL_TOOL_TIMEOUT_HEADROOM_SECONDS


def test_prefer_pwsh_falls_back_to_inbox_windows_powershell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    monkeypatch.setattr(
        "magi.tools.builtin.powershell_tool._resolve_powershell_executable",
        lambda: None,
    )
    monkeypatch.setattr(
        "magi.tools.builtin.powershell_tool._well_known_windows_powershell_executable",
        lambda: fallback,
    )

    assert PowerShellTool._select_executable(prefer_pwsh=True) == fallback


def test_inbox_windows_powershell_uses_system_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = r"D:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    fake_os = SimpleNamespace(
        name="nt",
        environ={"SystemRoot": r"D:\Windows"},
        path=SimpleNamespace(
            join=ntpath.join,
            isfile=lambda path: path == expected,
        ),
    )
    monkeypatch.setattr("magi.tools.builtin.powershell_tool.os", fake_os)

    assert _well_known_windows_powershell_executable() == expected


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
    monkeypatch.setattr(
        "magi.tools.builtin.powershell_tool._well_known_windows_powershell_executable",
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
    assert result.data["stdout_total_bytes"] >= len("测试-OK".encode("utf-8"))
    assert result.data["stdout_truncated"] is False
    assert result.data["timed_out"] is False


@pytest.mark.asyncio
async def test_powershell_timeout_keeps_partial_output_and_bounded_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, dict[str, object]]] = []
    spill_path = Path("C:/temp/full-powershell-stdout.bin")

    async def fake_run(command: object, **kwargs: object) -> BoundedSubprocessResult:
        calls.append((command, kwargs))
        return BoundedSubprocessResult(
            returncode=1,
            stdout=BoundedStreamOutput(
                tail="部分输出".encode("utf-8"),
                total_bytes=90_000,
                truncated=True,
                spill_path=spill_path,
            ),
            stderr=BoundedStreamOutput(
                tail="等待超时".encode("utf-8"),
                total_bytes=len("等待超时".encode("utf-8")),
                truncated=False,
                spill_path=None,
            ),
            timed_out=True,
        )

    monkeypatch.setattr(
        "magi.tools.builtin.powershell_tool.run_bounded_subprocess",
        fake_run,
    )
    monkeypatch.setattr(
        PowerShellTool,
        "_select_executable",
        staticmethod(lambda _prefer_pwsh: "powershell.exe"),
    )
    tool = PowerShellTool()
    result = await tool.execute(
        {"command": "Write-Output hi", "cwd": ".", "timeout": 9},
        _context(),
    )

    assert result.success is False
    assert result.error_code == "TIMEOUT"
    assert result.data["stdout"] == "部分输出"
    assert result.data["stderr"] == "等待超时"
    assert result.data["stdout_total_bytes"] == 90_000
    assert result.data["stdout_truncated"] is True
    assert result.data["stdout_spill_path"] == str(spill_path)
    assert result.data["timed_out"] is True
    command, kwargs = calls[0]
    assert isinstance(command, list)
    assert command[0] == "powershell.exe"
    assert "-NonInteractive" in command
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 9
    assert kwargs["max_spill_bytes"] == 0
