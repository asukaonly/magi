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


AGENT_TOOL_DESCRIPTION = (
    "Delegate a concrete, self-contained subtask to a child agent when independent "
    "execution offers a clear benefit: parallel progress, isolating substantial "
    "work from the main conversation, or an independent review.\n\n"
    "Handle simple factual lookups, single-page reads, short checks, and immediate "
    "blocking steps directly with the relevant tools. If a needed capability is "
    "missing, use find-relevant-tools; do not launch a child merely to obtain tools.\n\n"
    "Give the child a clear goal, necessary context, a bounded scope, and the "
    "expected output. Avoid duplicating its work. Review its evidence and integrate "
    "the result into your answer.\n\n"
    "Launch waits for the result by default. Set run_in_background=true when you "
    "can continue useful work independently, then use status, await, or cancel with "
    "the returned child IDs. Wait only when the result is needed for your next step."
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
            description=AGENT_TOOL_DESCRIPTION,
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
            description=(
                "Capability policy, not a task category. Use only: default "
                "(read-only), read_only (read-only tools), workspace_write "
                "(read and local-write tools), or review (read-only with a higher "
                "baseline reasoning depth). Put the task itself in prompt."
            ),
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
            description=(
                "Self-contained assignment with a clear goal, necessary context, "
                "bounded scope, and expected output. The child does not receive "
                "the parent conversation by default."
            ),
            required=False,
        ),
        ToolParameter(
            name="workers",
            type=ParameterType.ARRAY,
            array_item_type=ParameterType.OBJECT,
            description=(
                "Batch worker definitions. Each item: "
                "{preset, description, prompt, max_iterations?}. Use the same "
                "allowed preset values and self-contained prompt requirements "
                "as a single launch. Give each child a distinct scope."
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
            description=(
                "Return immediately with child IDs when true; otherwise wait for "
                "results. Use true when you can continue useful work independently."
            ),
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
                "Pass a bounded summary of the parent conversation when true, "
                "not the full history. When false (default), the child receives "
                "only the assignment prompt as conversation context. Include "
                "essential details in prompt even when enabled."
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
                "preset": "review",
                "description": "review authentication error handling",
                "prompt": (
                    "Independently review the authentication implementation in "
                    "the current workspace for missing token validation and "
                    "incorrect error handling. Trace the relevant request paths. "
                    "Do not edit files. Return actionable findings with file and "
                    "line references, supporting evidence, and any uncertainties."
                ),
                "run_in_background": True,
            },
            "output": "Returns child IDs and status for later status, await, or cancel",
        }
    ]
