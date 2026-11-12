"""Inspect and stop shell jobs without reissuing their commands."""

from typing import Any

from ..platform_tools import native_shell_tool_name
from ..schema import ParameterType, Tool, ToolExecutionContext, ToolParameter, ToolResult, ToolSchema


class ShellJobTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="shell_job",
            description=(
                "List, poll, wait for, or stop shell jobs started by this conversation. "
                "A running job has not finished. Inspect its exit code before claiming a build or test passed. "
                "Use this tool instead of starting the same command again."
            ),
            category="system",
            parameters=[
                ToolParameter(name="action", type=ParameterType.STRING, description="Job operation", enum=["list", "poll", "wait", "stop"], required=True),
                ToolParameter(name="job_id", type=ParameterType.STRING, description="Job returned by the native shell tool"),
                ToolParameter(name="wait_seconds", type=ParameterType.INTEGER, default=30, min_value=0,
                              description="Wait at most 30 seconds per observation; the job keeps running."),
            ],
            timeout=50,
            retry_on_failure=False,
            effect_class="local_write",
            effect_replay_policy="idempotent",
            metadata={"read_only_actions": ["list", "poll", "wait"], "domains": ["runtime"], "operations": ["inspect", "stop"]},
        )

    async def execute(self, parameters: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        registry = getattr(self, "_tool_registry_ref", None)
        shell = registry.get_tool(native_shell_tool_name()) if registry is not None else None
        if shell is None:
            return ToolResult(success=False, error="Native shell is unavailable.", error_code="UNSUPPORTED")
        return await shell.jobs.control(parameters, context)
