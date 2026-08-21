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
from dataclasses import dataclass
from typing import Any, Dict

from magi_plugin_sdk.subprocess import hidden_process_kwargs
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
from ._bash_grading import classify_command

_UTF8_PRELUDE = (
    "$ErrorActionPreference = 'Stop'; "
    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
    "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new(); "
    "$OutputEncoding = [System.Text.UTF8Encoding]::new(); "
    "$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'; "
)


@dataclass(frozen=True)
class _PowerShellRequest:
    command: str
    cwd: str
    timeout: int
    prefer_pwsh: bool
    confirm_destructive: bool


@dataclass(frozen=True)
class _PowerShellOutput:
    return_code: int | None
    stdout: str
    stderr: str
    stdout_encoding: str
    stderr_encoding: str


def _resolve_powershell_executable() -> str | None:
    """Return the best PowerShell executable available, or None."""
    for candidate in ("pwsh", "powershell"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _powershell_parameters() -> list[ToolParameter]:
    return [
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
        ToolParameter(
            name="confirm_destructive",
            type=ParameterType.BOOLEAN,
            description=(
                "Required to execute commands classified as destructive "
                "(e.g. Remove-Item -Recurse -Force, Format-Volume, "
                "Stop-Computer). Default false."
            ),
            required=False,
            default=False,
        ),
    ]


def _powershell_examples() -> list[dict[str, Any]]:
    return [
        {
            "input": {
                "command": (
                    "Get-Process | Select-Object -First 3 Name,Id | " "ConvertTo-Json -Compress"
                )
            },
            "output": "Returns the first three processes as JSON.",
        },
        {
            "input": {"command": "Get-Service Spooler | ConvertTo-Json -Compress"},
            "output": "Returns the print spooler service status as JSON.",
        },
    ]


def _powershell_request(
    parameters: Dict[str, Any],
    context: ToolExecutionContext,
) -> _PowerShellRequest:
    return _PowerShellRequest(
        command=parameters["command"],
        cwd=parameters.get("cwd", context.workspace),
        timeout=parameters.get("timeout", 60),
        prefer_pwsh=bool(parameters.get("prefer_pwsh", True)),
        confirm_destructive=bool(parameters.get("confirm_destructive", False)),
    )


def _risk_data(command: str) -> dict[str, str]:
    grade = classify_command(command)
    return {"risk_level": grade.level, "risk_reason": grade.reason}


def _destructive_block_result(risk_data: dict[str, str]) -> ToolResult:
    return ToolResult(
        success=False,
        error=(
            f"Command refused: classified as destructive ({risk_data['risk_reason']}). "
            "Pass confirm_destructive=true to execute, or rewrite to a "
            "narrower form."
        ),
        error_code=ToolErrorCode.POLICY_BLOCKED.value,
        data=risk_data,
    )


def _unsupported_result(risk_data: dict[str, str]) -> ToolResult:
    return ToolResult(
        success=False,
        error="PowerShell not found (neither 'pwsh' nor 'powershell' on PATH)",
        error_code=ToolErrorCode.UNSUPPORTED.value,
        data=risk_data,
    )


def _argv(executable: str, command: str) -> list[str]:
    return [
        executable,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-OutputFormat",
        "Text",
        "-Command",
        _UTF8_PRELUDE + command,
    ]


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
            parameters=_powershell_parameters(),
            examples=_powershell_examples(),
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
        request = _powershell_request(parameters, context)
        risk_data = _risk_data(request.command)
        if risk_data["risk_level"] == "destructive" and not request.confirm_destructive:
            return _destructive_block_result(risk_data)

        executable = self._select_executable(request.prefer_pwsh)
        if executable is None:
            return _unsupported_result(risk_data)

        try:
            output = await self._run_powershell(executable, request, risk_data)
            if isinstance(output, ToolResult):
                return output
            return self._result_from_output(
                executable=executable,
                request=request,
                output=output,
                risk_data=risk_data,
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                error=f"Working directory not found: {request.cwd}",
                error_code=ToolErrorCode.DIRECTORY_NOT_FOUND.value,
                data=risk_data,
            )
        except Exception as exc:  # noqa: BLE001 - surface as tool error
            return ToolResult(
                success=False,
                error=str(exc),
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
                data=risk_data,
            )

    async def _run_powershell(
        self,
        executable: str,
        request: _PowerShellRequest,
        risk_data: dict[str, str],
    ) -> _PowerShellOutput | ToolResult:
        process = await asyncio.create_subprocess_exec(
            *_argv(executable, request.command),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=request.cwd,
            env=_build_subprocess_env(),
            **hidden_process_kwargs(),
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=request.timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return ToolResult(
                success=False,
                error=f"PowerShell command timed out after {request.timeout}s",
                error_code=ToolErrorCode.TIMEOUT.value,
                data=risk_data,
            )

        stdout_text, stdout_encoding = (
            _decode_process_output_with_encoding(stdout) if stdout else ("", "utf-8")
        )
        stderr_text, stderr_encoding = (
            _decode_process_output_with_encoding(stderr) if stderr else ("", "utf-8")
        )
        return _PowerShellOutput(
            return_code=process.returncode,
            stdout=stdout_text,
            stderr=stderr_text,
            stdout_encoding=stdout_encoding,
            stderr_encoding=stderr_encoding,
        )

    def _result_from_output(
        self,
        *,
        executable: str,
        request: _PowerShellRequest,
        output: _PowerShellOutput,
        risk_data: dict[str, str],
    ) -> ToolResult:
        result_data = {
            "executable": executable,
            "command": request.command,
            "return_code": output.return_code,
            "stdout": output.stdout,
            "stderr": output.stderr,
            "stdout_encoding": output.stdout_encoding,
            "stderr_encoding": output.stderr_encoding,
            **risk_data,
        }
        return ToolResult(
            success=output.return_code == 0,
            data=result_data,
            error=output.stderr if output.return_code != 0 else None,
            error_code=(ToolErrorCode.COMMAND_FAILED.value if output.return_code != 0 else None),
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
