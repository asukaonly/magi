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
    ACTION_CANCEL: str
    PRESET_DEFAULT: str
    PRESET_READ_ONLY: str
    PRESET_WORKSPACE_WRITE: str
    PRESET_REVIEW: str
    schema: ToolSchema


class WorkerSchemaMixin:
    """Build the public tool schema for launching and awaiting worker agents."""

    def _init_schema(self) -> None:
        host = cast(_WorkerSchemaHostProtocol, self)
        host.schema = ToolSchema(
            name="agent",
            description=(
                "Launch and control bounded child agent runs. Presets constrain "
                "capabilities and reasoning without classifying task semantics."
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
        *_context_parameters(),
    ]


def _action_parameters(host: _WorkerSchemaHostProtocol) -> list[ToolParameter]:
    return [
        ToolParameter(
            name="action",
            type=ParameterType.STRING,
            description="Action: launch, status, await, or cancel",
            required=False,
            default=host.ACTION_LAUNCH,
            enum=[
                host.ACTION_LAUNCH,
                host.ACTION_STATUS,
                host.ACTION_AWAIT,
                host.ACTION_CANCEL,
            ],
        ),
        ToolParameter(
            name="worker_id",
            type=ParameterType.STRING,
            description="Child id for status, await, or cancel actions",
            required=False,
        ),
        ToolParameter(
            name="worker_ids",
            type=ParameterType.ARRAY,
            array_item_type=ParameterType.STRING,
            description="Multiple child ids for batch status, await, or cancel actions",
            required=False,
        ),
    ]


def _launch_parameters(host: _WorkerSchemaHostProtocol) -> list[ToolParameter]:
    return [
        ToolParameter(
            name="preset",
            type=ParameterType.STRING,
            description="Capability preset: default, read_only, workspace_write, or review",
            required=False,
            default=host.PRESET_DEFAULT,
            enum=[
                host.PRESET_DEFAULT,
                host.PRESET_READ_ONLY,
                host.PRESET_WORKSPACE_WRITE,
                host.PRESET_REVIEW,
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
                "{preset, description, prompt, max_iterations?}"
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


def _context_parameters() -> list[ToolParameter]:
    return [
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
    ]


def build_worker_schema_examples() -> list[dict[str, object]]:
    return [
        {
            "input": {
                "action": "launch",
                "preset": "read_only",
                "description": "scan auth flow",
                "prompt": "Find where JWT token is created and validated.",
            },
            "output": "Returns worker id and status",
        }
    ]
