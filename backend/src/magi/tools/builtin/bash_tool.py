"""
Bash命令执行工具
"""
import asyncio
import subprocess
from typing import Dict, Any
from ..schema import Tool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType


class BashTool(Tool):
    """
    Bash命令执行工具

    执行Shell命令并返回结果
    """

    def _init_schema(self) -> None:
        """初始化Schema"""
        self.schema = ToolSchema(
            name="bash",
            description="执行Bash/Shell命令",
            category="system",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="command",
                    type=ParameterType.STRING,
                    description="要执行的命令",
                    required=True,
                ),
                ToolParameter(
                    name="cwd",
                    type=ParameterType.STRING,
                    description="工作目录",
                    required=False,
                    default=".",
                ),
                ToolParameter(
                    name="timeout",
                    type=ParameterType.INTEGER,
                    description="超时时间（秒）",
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
            dangerous=True,  # 执行命令是危险操作
            tags=["system", "shell", "command"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """执行Bash命令"""
        command = parameters["command"]
        cwd = parameters.get("cwd", context.workspace)
        timeout = parameters.get("timeout", 30)

        try:
            # 执行命令
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            # 等待完成（带超时）
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )

                return_code = process.returncode

                # 准备结果
                result_data = {
                    "command": command,
                    "return_code": return_code,
                    "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                    "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
                }

                # 根据返回码判断是否成功
                return ToolResult(
                    success=return_code == 0,
                    data=result_data,
                    error=result_data["stderr"] if return_code != 0 else None,
                    error_code="COMMAND_FAILED" if return_code != 0 else None,
                )

            except asyncio.TimeoutError:
                # 超时，杀死进程
                process.kill()
                await process.wait()

                return ToolResult(
                    success=False,
                    error=f"Command execution timeout after {timeout}s",
                    error_code="TIMEOUT"
                )

        except FileNotFoundError:
            return ToolResult(
                success=False,
                error=f"Working directory not found: {cwd}",
                error_code="DIR_NOT_FOUND"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code="EXECUTION_ERROR"
            )
