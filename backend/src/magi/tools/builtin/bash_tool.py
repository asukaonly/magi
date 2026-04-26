"""
Bash command execution tool
"""
import asyncio
import ctypes
import locale
import os
from typing import Dict, Any
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType, ToolErrorCode


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


def _decode_process_output(output: bytes) -> str:
    """Decode subprocess output by trying candidate encodings (legacy helper)."""
    text, _ = _decode_process_output_with_encoding(output)
    return text


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
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    if os.name != "nt":
        # Avoid clobbering an explicit non-UTF-8 locale if the operator set one.
        if not any(env.get(key) for key in ("LC_ALL", "LANG")):
            env["LC_ALL"] = "C.UTF-8"
            env["LANG"] = "C.UTF-8"
    return env


class BashTool(Tool):
    """
    Bash command execution tool

    Executes Shell commands and returns results
    """

    def _init_schema(self) -> None:
        """initialize Schema"""
        self.schema = ToolSchema(
            name="bash",
            description=(
                "Execute Bash/Shell commands. Use this for running external programs "
                "(git, build tools, scripts, package managers). Do NOT use this to list "
                "directories or read file metadata — prefer the structured `file_list`, "
                "`file_info`, `file_read`, `glob`, and `grep` tools, which return JSON "
                "and avoid Windows console-encoding issues."
            ),
            category="system",
            version="1.0.0",
            author="Magi Team",
            parameters=[
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
            ],
            examples=[
                {
                    "input": {"command": "ls -la", "cwd": "."},
                    "output": "Lists all files in current directory",
                },
                {
                    "input": {"command": "pwd"},
                    "output": "Prints current working directory",
                },
            ],
            timeout=60,
            retry_on_failure=False,
            dangerous=True,  # Executing commands is a dangerous operation
            tags=["system", "shell", "command"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute Bash command"""
        command = parameters["command"]
        cwd = parameters.get("cwd", context.workspace)
        timeout = parameters.get("timeout", 30)

        try:
            # Execute command
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=_build_subprocess_env(),
            )

            # Wait for completion (with timeout)
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )

                return_code = process.returncode

                stdout_text, stdout_encoding = (
                    _decode_process_output_with_encoding(stdout) if stdout else ("", "utf-8")
                )
                stderr_text, stderr_encoding = (
                    _decode_process_output_with_encoding(stderr) if stderr else ("", "utf-8")
                )

                # Prepare result
                result_data = {
                    "command": command,
                    "return_code": return_code,
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "stdout_encoding": stdout_encoding,
                    "stderr_encoding": stderr_encoding,
                }

                # Determine success based on return code
                return ToolResult(
                    success=return_code == 0,
                    data=result_data,
                    error=result_data["stderr"] if return_code != 0 else None,
                    error_code=ToolErrorCode.COMMAND_FAILED.value if return_code != 0 else None,
                )

            except asyncio.TimeoutError:
                # Timeout, kill the process
                process.kill()
                await process.wait()

                return ToolResult(
                    success=False,
                    error=f"Command execution timeout after {timeout}s",
                    error_code=ToolErrorCode.TIMEOUT.value
                )

        except FileNotFoundError:
            return ToolResult(
                success=False,
                error=f"Working directory not found: {cwd}",
                error_code=ToolErrorCode.DIRECTORY_NOT_FOUND.value
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code=ToolErrorCode.EXECUTION_ERROR.value
            )
