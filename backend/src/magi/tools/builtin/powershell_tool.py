"""Windows PowerShell execution tool.

Targeted at Windows-specific automation (registry, services, WMI/CIM,
COM, scheduled tasks, etc.) where there is no clean Python alternative.
The tool forces UTF-8 input/output encodings inside PowerShell so that
captured stdout/stderr decode cleanly regardless of the host console
code page. For generic file system enumeration prefer the structured
``file_list`` / ``file_info`` tools.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any, Dict

from ..schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)
from .bash_tool import _build_subprocess_env, _decode_process_output_with_encoding


_UTF8_PRELUDE = (
    "$ErrorActionPreference = 'Stop'; "
    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
    "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new(); "
    "$OutputEncoding = [System.Text.UTF8Encoding]::new(); "
    "$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'; "
)


def _resolve_powershell_executable() -> str | None:
    """Return the best PowerShell executable available, or None."""
    for candidate in ("pwsh", "powershell"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


class PowerShellTool(Tool):
    """Run a PowerShell command on Windows with UTF-8 output enforced."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="powershell",
            description=(
                "Execute a PowerShell command. Intended for Windows-specific "
                "automation (registry, services, WMI/CIM, scheduled tasks, "
                "COM, Get-Process, Get-CimInstance, etc.). Output encoding is "
                "forced to UTF-8 inside the PowerShell session. For generic "
                "file system enumeration prefer the `file_list` / `file_info` "
                "tools; for cross-platform shell execution prefer `bash`. Tip: "
                "end pipelines with `| ConvertTo-Json -Depth 4 -Compress` so "
                "the agent receives structured data instead of formatted "
                "tables."
            ),
            category="system",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="command",
                    type=ParameterType.STRING,
                    description="PowerShell command or script block to execute",
                    required=True,
                ),
                ToolParameter(
                    name="cwd",
                    type=ParameterType.STRING,
                    description="Working directory",
                    required=False,
                    default=".",
                ),
                ToolParameter(
                    name="timeout",
                    type=ParameterType.INTEGER,
                    description="Timeout (seconds)",
                    required=False,
                    default=60,
                    min_value=1,
                    max_value=600,
                ),
                ToolParameter(
                    name="prefer_pwsh",
                    type=ParameterType.BOOLEAN,
                    description="Prefer pwsh (PowerShell 7+) when available",
                    required=False,
                    default=True,
                ),
            ],
            examples=[
                {
                    "input": {"command": "Get-Process | Select-Object -First 3 Name,Id | ConvertTo-Json -Compress"},
                    "output": "Returns the first three processes as JSON.",
                },
                {
                    "input": {"command": "Get-Service Spooler | ConvertTo-Json -Compress"},
                    "output": "Returns the print spooler service status as JSON.",
                },
            ],
            timeout=120,
            retry_on_failure=False,
            dangerous=True,
            tags=["system", "windows", "powershell", "shell"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        command = parameters["command"]
        cwd = parameters.get("cwd", context.workspace)
        timeout = parameters.get("timeout", 60)
        prefer_pwsh = bool(parameters.get("prefer_pwsh", True))

        executable = self._select_executable(prefer_pwsh)
        if executable is None:
            return ToolResult(
                success=False,
                error="PowerShell not found (neither 'pwsh' nor 'powershell' on PATH)",
                error_code=ToolErrorCode.UNSUPPORTED.value,
            )

        wrapped_command = _UTF8_PRELUDE + command
        argv = [
            executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-OutputFormat",
            "Text",
            "-Command",
            wrapped_command,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=_build_subprocess_env(),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    success=False,
                    error=f"PowerShell command timed out after {timeout}s",
                    error_code=ToolErrorCode.TIMEOUT.value,
                )

            return_code = process.returncode
            stdout_text, stdout_encoding = (
                _decode_process_output_with_encoding(stdout) if stdout else ("", "utf-8")
            )
            stderr_text, stderr_encoding = (
                _decode_process_output_with_encoding(stderr) if stderr else ("", "utf-8")
            )

            result_data = {
                "executable": executable,
                "command": command,
                "return_code": return_code,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "stdout_encoding": stdout_encoding,
                "stderr_encoding": stderr_encoding,
            }

            return ToolResult(
                success=return_code == 0,
                data=result_data,
                error=stderr_text if return_code != 0 else None,
                error_code=ToolErrorCode.COMMAND_FAILED.value if return_code != 0 else None,
            )

        except FileNotFoundError:
            return ToolResult(
                success=False,
                error=f"Working directory not found: {cwd}",
                error_code=ToolErrorCode.DIRECTORY_NOT_FOUND.value,
            )
        except Exception as exc:  # noqa: BLE001 - surface as tool error
            return ToolResult(
                success=False,
                error=str(exc),
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
            )

    @staticmethod
    def _select_executable(prefer_pwsh: bool) -> str | None:
        if prefer_pwsh:
            return _resolve_powershell_executable()

        # Caller explicitly asked for the legacy host first.
        for candidate in ("powershell", "pwsh"):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved

        # Last resort: well-known location on Windows installations.
        if os.name == "nt":
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            fallback = os.path.join(
                system_root,
                "System32",
                "WindowsPowerShell",
                "v1.0",
                "powershell.exe",
            )
            if os.path.isfile(fallback):
                return fallback
        return None
