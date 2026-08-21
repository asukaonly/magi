"""
Bash command execution tool
"""

import ctypes
import locale
import os
from dataclasses import dataclass
from typing import Dict, Any
from magi_plugin_sdk.subprocess import (
    BoundedStreamOutput,
    BoundedSubprocessResult,
    run_bounded_subprocess,
)
from ..schema import (
    Tool,
    ToolSchema,
    ToolExecutionContext,
    ToolResult,
    ToolParameter,
    ParameterType,
    ToolErrorCode,
)
from ._bash_grading import classify_command

_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


def _windows_code_page_encoding(function_name: str) -> str | None:
    if os.name != "nt":
        return None

    try:
        code_page = getattr(ctypes.windll.kernel32, function_name)()
    except (AttributeError, OSError):
        return None

    return f"cp{code_page}" if code_page else None


def _candidate_output_encodings() -> list[str]:
    encodings = ["utf-8-sig", "utf-8"]

    if os.name == "nt":
        encodings.extend(
            encoding
            for encoding in (
                _windows_code_page_encoding("GetConsoleOutputCP"),
                _windows_code_page_encoding("GetOEMCP"),
                _windows_code_page_encoding("GetACP"),
                locale.getpreferredencoding(False),
                "mbcs",
            )
            if encoding
        )
    else:
        preferred_encoding = locale.getpreferredencoding(False)
        if preferred_encoding:
            encodings.append(preferred_encoding)

    unique_encodings = []
    for encoding in encodings:
        normalized = encoding.lower()
        if normalized not in {item.lower() for item in unique_encodings}:
            unique_encodings.append(encoding)
    return unique_encodings


def _decode_process_output_with_encoding(output: bytes) -> tuple[str, str]:
    """Decode subprocess output and return the encoding that succeeded.

    Tries strict UTF-8 first, then platform-specific code pages, then a
    lossy UTF-8 fallback. Reporting the encoding back to the caller lets
    upstream telemetry distinguish "happy path" decodes from "we had to
    fall back to cp936" decodes — important on Windows where ``cmd.exe``
    builtins ignore ``chcp 65001`` and emit OEM-CP bytes regardless.
    """
    for encoding in _candidate_output_encodings():
        try:
            return output.decode(encoding), encoding
        except (LookupError, UnicodeDecodeError):
            continue
    return output.decode("utf-8", errors="replace"), "utf-8/replace"


def _build_subprocess_env() -> dict[str, str]:
    """Return an env dict that nudges child processes toward UTF-8 output.

    These hints are best-effort: ``cmd.exe`` builtins (``dir``, ``type``)
    will still emit OEM-CP bytes regardless. For reliable file-system
    introspection prefer the structured ``file_list`` / ``file_info``
    tools.
    """
    env = os.environ.copy()
    for key in _PROXY_ENV_KEYS:
        env.pop(key, None)

    try:
        from ...config import get_config

        proxy_url = get_config().network.proxy_url()
    except Exception:
        proxy_url = None

    if proxy_url:
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            env[key] = proxy_url

    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    if os.name != "nt":
        # Avoid clobbering an explicit non-UTF-8 locale if the operator set one.
        if not any(env.get(key) for key in ("LC_ALL", "LANG")):
            env["LC_ALL"] = "C.UTF-8"
            env["LANG"] = "C.UTF-8"
    return env


@dataclass(frozen=True)
class _BashRequest:
    command: str
    cwd: str
    timeout: int
    confirm_destructive: bool


@dataclass(frozen=True)
class _ShellOutput:
    process: BoundedSubprocessResult
    stdout: str
    stderr: str
    stdout_encoding: str
    stderr_encoding: str


def _bash_request(
    parameters: Dict[str, Any],
    context: ToolExecutionContext,
) -> _BashRequest:
    return _BashRequest(
        command=parameters["command"],
        cwd=parameters.get("cwd", context.workspace),
        timeout=parameters.get("timeout", 30),
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


def _decode_bounded_stream(stream: BoundedStreamOutput) -> tuple[str, str]:
    if not stream.tail:
        return "", "utf-8"
    if stream.truncated:
        return stream.tail.decode("utf-8", errors="replace"), "utf-8/replace"
    return _decode_process_output_with_encoding(stream.tail)


def _decode_bounded_process_output(result: BoundedSubprocessResult) -> _ShellOutput:
    stdout_text, stdout_encoding = _decode_bounded_stream(result.stdout)
    stderr_text, stderr_encoding = _decode_bounded_stream(result.stderr)
    return _ShellOutput(
        process=result,
        stdout=stdout_text,
        stderr=stderr_text,
        stdout_encoding=stdout_encoding,
        stderr_encoding=stderr_encoding,
    )


def _bounded_output_data(output: _ShellOutput) -> dict[str, Any]:
    process = output.process
    return {
        "return_code": process.returncode,
        "stdout": output.stdout,
        "stderr": output.stderr,
        "stdout_encoding": output.stdout_encoding,
        "stderr_encoding": output.stderr_encoding,
        "stdout_total_bytes": process.stdout.total_bytes,
        "stderr_total_bytes": process.stderr.total_bytes,
        "stdout_truncated": process.stdout.truncated,
        "stderr_truncated": process.stderr.truncated,
        "stdout_spill_path": (
            str(process.stdout.spill_path) if process.stdout.spill_path is not None else None
        ),
        "stderr_spill_path": (
            str(process.stderr.spill_path) if process.stderr.spill_path is not None else None
        ),
        "timed_out": process.timed_out,
    }


def _bash_description() -> str:
    return (
        "Execute Bash/Shell commands on POSIX hosts. Use this for running "
        "external programs "
        "(git, build tools, scripts, package managers). Do NOT use this to list "
        "directories or read file metadata — prefer the structured `file_list`, "
        "`file_info`, `file_read`, `glob`, and `grep` tools, which return JSON "
        "and avoid Windows console-encoding issues. "
        "For outbound web requests, prefer `web-search`, `web-fetch`, or `weather`; "
        "when shell networking is necessary, rely on the subprocess proxy environment "
        "generated from Magi network settings and do not hardcode proxy hosts or ports. "
        "Destructive commands (rm -rf, git push --force, git reset --hard, etc.) "
        "are refused unless confirm_destructive=true is passed explicitly."
    )


def _bash_parameters() -> list[ToolParameter]:
    return [
        ToolParameter(
            name="command",
            type=ParameterType.STRING,
            description="Command to execute",
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
            default=30,
            min_value=1,
            max_value=300,
        ),
        ToolParameter(
            name="confirm_destructive",
            type=ParameterType.BOOLEAN,
            description=(
                "Required to execute commands classified as destructive "
                "(e.g. rm -rf, git push --force, git reset --hard). "
                "Default false."
            ),
            required=False,
            default=False,
        ),
    ]


def _bash_examples() -> list[dict[str, Any]]:
    return [
        {
            "input": {"command": "ls -la", "cwd": "."},
            "output": "Lists all files in current directory",
        },
        {
            "input": {"command": "pwd"},
            "output": "Prints current working directory",
        },
    ]


def _bash_metadata() -> dict[str, Any]:
    return {
        "task_intents": ["debug_runtime", "inspect_runtime_state"],
        "domains": ["runtime", "system"],
        "operations": ["probe", "inspect"],
        "query_shapes": ["shell_command", "one_off_check"],
        "followed_by": ["file_read", "file_edit"],
        "avoid_task_intents": [
            "research_external",
            "clarify_requirement",
            "recall_context",
        ],
        "cost": "medium",
        "tool_hint": "Use for narrow executable checks, environment inspection, or reproducing a suspected behavior once the target is already known.",
    }


class BashTool(Tool):
    """
    Bash command execution tool

    Executes Shell commands and returns results
    """

    def _init_schema(self) -> None:
        """initialize Schema"""
        self.schema = ToolSchema(
            name="bash",
            description=_bash_description(),
            category="system",
            version="1.0.0",
            author="Magi Team",
            parameters=_bash_parameters(),
            examples=_bash_examples(),
            timeout=60,
            retry_on_failure=False,
            dangerous=True,  # Executing commands is a dangerous operation
            tags=["system", "shell", "command"],
            metadata=_bash_metadata(),
        )

    async def execute(
        self, parameters: Dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        """Execute Bash command"""
        request = _bash_request(parameters, context)
        risk_data = _risk_data(request.command)
        if risk_data["risk_level"] == "destructive" and not request.confirm_destructive:
            return _destructive_block_result(risk_data)

        try:
            output = await self._run_bash(request)
            return self._result_from_output(request, output, risk_data)

        except FileNotFoundError:
            return ToolResult(
                success=False,
                error=f"Working directory not found: {request.cwd}",
                error_code=ToolErrorCode.DIRECTORY_NOT_FOUND.value,
                data=risk_data,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
                data=risk_data,
            )

    async def _run_bash(
        self,
        request: _BashRequest,
    ) -> _ShellOutput:
        result = await run_bounded_subprocess(
            request.command,
            shell=True,
            timeout=request.timeout,
            cwd=request.cwd,
            env=_build_subprocess_env(),
            max_spill_bytes=0,
        )
        return _decode_bounded_process_output(result)

    def _result_from_output(
        self,
        request: _BashRequest,
        output: _ShellOutput,
        risk_data: dict[str, str],
    ) -> ToolResult:
        result_data = {
            "command": request.command,
            **_bounded_output_data(output),
            **risk_data,
        }
        if output.process.timed_out:
            return ToolResult(
                success=False,
                error=f"Command execution timeout after {request.timeout}s",
                error_code=ToolErrorCode.TIMEOUT.value,
                data=result_data,
            )
        return ToolResult(
            success=output.process.returncode == 0,
            data=result_data,
            error=output.stderr if output.process.returncode != 0 else None,
            error_code=(
                ToolErrorCode.COMMAND_FAILED.value if output.process.returncode != 0 else None
            ),
        )
