"""Agent tool facade for launching specialized worker agents."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ..workers import (
    WorkerAgentManager,
    WorkerRunState,
    WORKER_AGENT_COMPLETED,
    WORKER_AGENT_FAILED,
    WORKER_AGENT_PROGRESS,
)
from ..workers.worker_state import (
    DEFAULT_WORKER_AWAIT_TIMEOUT_SECONDS,
    DEFAULT_WORKER_MAX_ITERATIONS,
    MAX_WORKER_AWAIT_TIMEOUT_SECONDS,
    MAX_WORKER_MAX_ITERATIONS,
    WORKER_TOOL_TIMEOUT_SECONDS,
)
from ..workers.worker_schema import (
    build_worker_schema_examples,
    build_worker_schema_parameters,
)

# L12 -> L8 downward (legal): the agent tool still hands its sub-agents a
# reference to the host tool registry so they can resolve their own tool set.
from magi.tools.registry import ToolRegistry

# Use the SDK contracts directly (SDK-consistent) rather than re-importing the
# host's magi.tools.schema re-exports.
from magi_plugin_sdk import (
    ParameterType,
    Tool,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)


class AgentTool(Tool):
    """Thin tool facade that delegates worker orchestration to WorkerAgentManager."""

    ACTION_LAUNCH = "launch"
    ACTION_STATUS = "status"
    ACTION_AWAIT = "await"

    TYPE_GENERAL = "general-purpose"
    TYPE_EXPLORE = "CodeExplore"
    TYPE_PLAN = "Plan"
    TYPE_CODING = "Coding"

    _WORKER_TYPE_MAP = {
        "general-purpose": TYPE_GENERAL,
        "general_purpose": TYPE_GENERAL,
        "general": TYPE_GENERAL,
        "code-explore": TYPE_EXPLORE,
        "code_explore": TYPE_EXPLORE,
        "CodeExplore": TYPE_EXPLORE,
        "plan": TYPE_PLAN,
        "Plan": TYPE_PLAN,
        "coding": TYPE_CODING,
        "Coding": TYPE_CODING,
        "code": TYPE_CODING,
    }

    def __init__(self) -> None:
        self._manager = WorkerAgentManager()
        super().__init__()

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="agent",
            description=(
                "Launch a specialized worker agent for complex tasks. "
                "Worker types: general-purpose, CodeExplore, Plan, Coding. "
                "Supports foreground wait and background execution."
            ),
            category="agent",
            version="1.0.0",
            author="Magi Team",
            parameters=_agent_tool_schema_parameters(self),
            examples=_agent_tool_schema_examples(),
            timeout=WORKER_TOOL_TIMEOUT_SECONDS,
            dangerous=False,
            effect_replay_policy="reconcilable",
            tags=["agent", "worker", "planning", "exploration"],
            metadata=_agent_tool_schema_metadata(),
        )

    def configure(
        self,
        llm_adapter,
        tool_registry_instance: Optional[ToolRegistry] = None,
        task_agent_manager=None,
        message_bus=None,
        runtime_trace_store=None,
        scenario_llm_pool=None,
        active_model_provider=None,
        permission_gateway_provider: Callable[[], Any] | None = None,
    ) -> None:
        """Inject runtime dependencies after bootstrap."""
        self._manager.configure(
            llm_adapter=llm_adapter,
            tool_registry_instance=tool_registry_instance,
            task_agent_manager=task_agent_manager,
            message_bus=message_bus,
            runtime_trace_store=runtime_trace_store,
            scenario_llm_pool=scenario_llm_pool,
            active_model_provider=active_model_provider,
            permission_gateway_provider=permission_gateway_provider,
        )

    async def validate_parameters(
        self,
        parameters: Dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        valid, error = await super().validate_parameters(parameters)
        if not valid:
            return valid, error
        return await self._manager.validate_parameters(parameters)

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        return await self._manager.execute(parameters=parameters, context=context)

    @property
    def _runs(self):
        return self._manager._runs

    def _resolve_tools_for_type(self, subagent_type: str):
        return self._manager._resolve_tools_for_type(subagent_type)

    def _build_worker_system_prompt(
        self,
        worker_id: str,
        subagent_type: str,
        description: str,
        selected_tools,
        execution_workspace: Optional[str] = None,
    ) -> str:
        return self._manager._build_worker_system_prompt(
            worker_id=worker_id,
            subagent_type=subagent_type,
            description=description,
            selected_tools=selected_tools,
            execution_workspace=execution_workspace,
        )

    async def _await_worker(self, worker_id: str, timeout_seconds: int) -> ToolResult:
        return await self._manager._await_worker(
            worker_id=worker_id, timeout_seconds=timeout_seconds
        )


def _agent_tool_schema_parameters(tool: AgentTool) -> list[ToolParameter]:
    return build_worker_schema_parameters(tool)


def _agent_action_parameters(tool: AgentTool) -> list[ToolParameter]:
    return [
        ToolParameter(
            name="action",
            type=ParameterType.STRING,
            description="Action: launch, status, or await",
            required=False,
            default=tool.ACTION_LAUNCH,
            enum=[tool.ACTION_LAUNCH, tool.ACTION_STATUS, tool.ACTION_AWAIT],
        ),
        ToolParameter(
            name="worker_id",
            type=ParameterType.STRING,
            description="Worker id for status/await actions",
            required=False,
        ),
        ToolParameter(
            name="worker_ids",
            type=ParameterType.ARRAY,
            array_item_type=ParameterType.STRING,
            description="Multiple worker ids for batch status/await actions",
            required=False,
        ),
    ]


def _agent_launch_parameters(tool: AgentTool) -> list[ToolParameter]:
    return [
        ToolParameter(
            name="subagent_type",
            type=ParameterType.STRING,
            description="Worker type: general-purpose, CodeExplore, Plan, or Coding",
            required=False,
            enum=[
                tool.TYPE_GENERAL,
                tool.TYPE_EXPLORE,
                tool.TYPE_PLAN,
                tool.TYPE_CODING,
                "code-explore",
                "code_explore",
                "plan",
                "coding",
                "general",
                "code",
            ],
        ),
        ToolParameter(
            name="description",
            type=ParameterType.STRING,
            description="Short 3-5 word task summary",
            required=False,
        ),
        ToolParameter(
            name="prompt",
            type=ParameterType.STRING,
            description="Detailed task instructions for the worker agent",
            required=False,
        ),
        ToolParameter(
            name="workers",
            type=ParameterType.ARRAY,
            array_item_type=ParameterType.OBJECT,
            description=(
                "Batch worker definitions. Each item: "
                "{subagent_type, description, prompt, target_task_agent_type?, "
                "target_task_agent_id?, max_iterations?}"
            ),
            required=False,
        ),
    ]


def _agent_execution_parameters() -> list[ToolParameter]:
    return [
        ToolParameter(
            name="parallel",
            type=ParameterType.BOOLEAN,
            description="Whether batch workers should run in parallel",
            required=False,
            default=True,
        ),
        ToolParameter(
            name="run_in_background",
            type=ParameterType.BOOLEAN,
            description="Run asynchronously and return immediately",
            required=False,
            default=False,
        ),
        ToolParameter(
            name="max_iterations",
            type=ParameterType.INTEGER,
            description="Maximum internal tool-loop iterations for this worker",
            required=False,
            default=DEFAULT_WORKER_MAX_ITERATIONS,
            min_value=1,
            max_value=MAX_WORKER_MAX_ITERATIONS,
        ),
        ToolParameter(
            name="timeout_seconds",
            type=ParameterType.INTEGER,
            description="Timeout in seconds for await action",
            required=False,
            default=DEFAULT_WORKER_AWAIT_TIMEOUT_SECONDS,
            min_value=1,
            max_value=MAX_WORKER_AWAIT_TIMEOUT_SECONDS,
        ),
    ]


def _agent_routing_parameters() -> list[ToolParameter]:
    return [
        ToolParameter(
            name="target_task_agent_type",
            type=ParameterType.STRING,
            description="Target task agent type to receive worker facts",
            required=False,
            default="chat",
        ),
        ToolParameter(
            name="target_task_agent_id",
            type=ParameterType.STRING,
            description="Target task agent id to receive worker facts",
            required=False,
        ),
        ToolParameter(
            name="orchestration_id",
            type=ParameterType.STRING,
            description="Parent orchestration id when this worker belongs to a decomposed task",
            required=False,
        ),
        ToolParameter(
            name="subtask_id",
            type=ParameterType.STRING,
            description="Subtask id within the parent orchestration",
            required=False,
        ),
    ]


def _agent_context_parameters() -> list[ToolParameter]:
    return [
        ToolParameter(
            name="parent_task_agent_type",
            type=ParameterType.STRING,
            description="Parent task agent type that owns this worker",
            required=False,
        ),
        ToolParameter(
            name="parent_task_agent_id",
            type=ParameterType.STRING,
            description="Parent task agent id that owns this worker",
            required=False,
        ),
        ToolParameter(
            name="inherit_context",
            type=ParameterType.BOOLEAN,
            description=(
                "Pass a summary of the parent conversation to "
                "the worker so it can use surrounding context."
            ),
            required=False,
            default=False,
        ),
        ToolParameter(
            name="retry_count",
            type=ParameterType.INTEGER,
            description="Retry attempt count for this worker launch",
            required=False,
            default=0,
            min_value=0,
            max_value=3,
        ),
    ]


def _agent_tool_schema_examples() -> list[dict[str, object]]:
    return build_worker_schema_examples()


def _agent_tool_schema_metadata() -> dict[str, object]:
    return {
        "task_intents": ["delegate_task", "explore_codebase", "research_external"],
        "domains": ["orchestration", "codebase", "web"],
        "operations": ["delegate"],
        "query_shapes": ["multi_step_task", "parallelizable_research"],
        "followed_by": [],
        "avoid_task_intents": ["verify_source_claim"],
        "cost": "high",
        "tool_hint": (
            "Use when the task is large enough to justify a worker, parallel "
            "exploration, or independent background execution; avoid for simple local checks."
        ),
    }


__all__ = [
    "AgentTool",
    "WorkerRunState",
    "WORKER_AGENT_PROGRESS",
    "WORKER_AGENT_COMPLETED",
    "WORKER_AGENT_FAILED",
]
