"""Tool schema definition for the worker agent manager."""

from __future__ import annotations

from typing import Protocol, cast

from ...tools.schema import ParameterType, ToolParameter, ToolSchema
from .worker_state import (
    DEFAULT_WORKER_AWAIT_TIMEOUT_SECONDS,
    DEFAULT_WORKER_MAX_ITERATIONS,
    MAX_WORKER_MAX_ITERATIONS,
    MAX_WORKER_AWAIT_TIMEOUT_SECONDS,
    WORKER_TOOL_TIMEOUT_SECONDS,
)


class _WorkerSchemaHostProtocol(Protocol):
    ACTION_LAUNCH: str
    ACTION_STATUS: str
    ACTION_AWAIT: str
    TYPE_GENERAL: str
    TYPE_EXPLORE: str
    TYPE_PLAN: str
    TYPE_CODING: str
    schema: ToolSchema


class WorkerSchemaMixin:
    """Build the public tool schema for launching and awaiting worker agents."""

    def _init_schema(self) -> None:
        host = cast(_WorkerSchemaHostProtocol, self)
        host.schema = ToolSchema(
            name="agent",
            description=(
                "Launch a specialized worker agent for complex tasks. "
                "Worker types: general-purpose, CodeExplore, Plan, Coding. "
                "Supports foreground wait and background execution."
            ),
            category="agent",
            version="1.0.0",
            author="Magi Team",
            parameters=build_worker_schema_parameters(host),
            examples=build_worker_schema_examples(),
            timeout=WORKER_TOOL_TIMEOUT_SECONDS,
            dangerous=False,
            tags=["agent", "worker", "planning", "exploration"],
        )


def build_worker_schema_parameters(
    host: _WorkerSchemaHostProtocol,
) -> list[ToolParameter]:
    return [
        *_action_parameters(host),
        *_launch_parameters(host),
        *_execution_parameters(),
        *_routing_parameters(),
        *_context_parameters(),
    ]


def _action_parameters(host: _WorkerSchemaHostProtocol) -> list[ToolParameter]:
    return [
        ToolParameter(
            name="action",
            type=ParameterType.STRING,
            description="Action: launch, status, or await",
            required=False,
            default=host.ACTION_LAUNCH,
            enum=[host.ACTION_LAUNCH, host.ACTION_STATUS, host.ACTION_AWAIT],
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


def _launch_parameters(host: _WorkerSchemaHostProtocol) -> list[ToolParameter]:
    return [
        ToolParameter(
            name="subagent_type",
            type=ParameterType.STRING,
            description="Worker type: general-purpose, CodeExplore, Plan, or Coding",
            required=False,
            enum=[
                host.TYPE_GENERAL,
                host.TYPE_EXPLORE,
                host.TYPE_PLAN,
                host.TYPE_CODING,
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


def _execution_parameters() -> list[ToolParameter]:
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


def _routing_parameters() -> list[ToolParameter]:
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
            description="Parent orchestration id when this worker belongs to a task decomposition",
            required=False,
        ),
        ToolParameter(
            name="subtask_id",
            type=ParameterType.STRING,
            description="Subtask id within the parent orchestration",
            required=False,
        ),
        ToolParameter(
            name="turn_id",
            type=ParameterType.STRING,
            description="Conversation turn id associated with the parent user request",
            required=False,
        ),
    ]


def _context_parameters() -> list[ToolParameter]:
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
                "Whether to pass a summary of the parent conversation "
                "to the worker. When false (default), workers start "
                "with a clean context and only see the prompt."
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


def build_worker_schema_examples() -> list[dict[str, object]]:
    return [
        {
            "input": {
                "action": "launch",
                "subagent_type": "CodeExplore",
                "description": "scan auth flow",
                "prompt": "Find where JWT token is created and validated.",
            },
            "output": "Returns worker id and status",
        }
    ]
