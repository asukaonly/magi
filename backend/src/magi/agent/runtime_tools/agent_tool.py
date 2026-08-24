"""Agent tool facade for launching specialized worker agents."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ..workers import (
    ChildRunCoordinator,
    WorkerRunState,
)
from ..workers.worker_state import WORKER_TOOL_TIMEOUT_SECONDS
from ..workers.worker_schema import (
    build_worker_schema_examples,
    build_worker_schema_parameters,
)
from ..workers.child_preset import ChildRunPreset

# L12 -> L8 downward (legal): the agent tool still hands its sub-agents a
# reference to the host tool registry so they can resolve their own tool set.
from magi.tools.registry import ToolRegistry

# Use the SDK contracts directly (SDK-consistent) rather than re-importing the
# host's magi.tools.schema re-exports.
from magi_plugin_sdk import Tool, ToolExecutionContext, ToolParameter, ToolResult, ToolSchema


class AgentTool(Tool):
    """Thin tool facade that delegates lifecycle governance to ChildRunCoordinator."""

    ACTION_LAUNCH = "launch"
    ACTION_STATUS = "status"
    ACTION_AWAIT = "await"
    ACTION_CANCEL = "cancel"
    PRESET_DEFAULT = ChildRunPreset.DEFAULT.value
    PRESET_READ_ONLY = ChildRunPreset.READ_ONLY.value
    PRESET_WORKSPACE_WRITE = ChildRunPreset.WORKSPACE_WRITE.value
    PRESET_REVIEW = ChildRunPreset.REVIEW.value

    def __init__(self) -> None:
        self._manager = ChildRunCoordinator()
        super().__init__()

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="agent",
            description=(
                "Launch and control bounded child agent runs. Select a capability "
                "preset, then use status, await, or cancel with returned child ids."
            ),
            category="agent",
            version="1.0.0",
            author="Magi Team",
            parameters=_agent_tool_schema_parameters(self),
            examples=_agent_tool_schema_examples(),
            timeout=WORKER_TOOL_TIMEOUT_SECONDS,
            dangerous=False,
            effect_class="external_write",
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
        background_task_manager: Any | None = None,
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
            background_task_manager=background_task_manager,
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

    def _resolve_tools_for_preset(self, preset: str):
        return self._manager._resolve_tools_for_preset(preset)

    def _build_worker_system_prompt(
        self,
        worker_id: str,
        preset: str,
        description: str,
        selected_tools,
        execution_workspace: Optional[str] = None,
    ) -> str:
        return self._manager._build_worker_system_prompt(
            worker_id=worker_id,
            preset=preset,
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
]
