"""
Bash command execution tool
"""
import asyncio
import subprocess
from typing import Dict, Any
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType, ToolErrorCode


class BashTool(Tool):
    """
    Bash command execution tool

    Executes Shell commands and returns results
    """

    def _init_schema(self) -> None:
        """initialize Schema"""
        self.schema = ToolSchema(
            name="bash",
            description="Execute Bash/Shell commands",
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
            metadata={
                "task_intents": ["debug_runtime", "inspect_runtime_state"],
                "domains": ["runtime", "system"],
                "operations": ["probe", "inspect"],
                "query_shapes": ["shell_command", "one_off_check"],
                "followed_by": ["file_read", "file_edit"],
                "avoid_task_intents": ["research_external", "clarify_requirement", "recall_context"],
                "cost": "medium",
                "tool_hint": "Use for narrow executable checks, environment inspection, or reproducing a suspected behavior once the target is already known.",
            },
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
            )

            # Wait for completion (with timeout)
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )

                return_code = process.returncode

                # Prepare result
                result_data = {
                    "command": command,
                    "return_code": return_code,
                    "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                    "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
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
