"""Internal contracts shared by function-calling tool executors."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

from ...cancel import CancelToken
from ..reasoning import ReasoningPolicy, ReasoningState
from .types import ToolCall, ToolCallResult


class _ToolRegistryProtocol(Protocol):
    def get_tool_info(self, tool_name: str) -> dict[str, Any] | None: ...

    async def execute(self, tool_name: str, arguments: dict[str, Any], context: Any) -> Any: ...


class _FunctionCallingToolExecutionHostProtocol(Protocol):
    skill_runner: Any
    tool_registry: _ToolRegistryProtocol
    _tool_invocation_service: Any
    _FILE_SCAN_TOOLS: set[str]
    _SLOW_SCAN_WARNING_SECONDS: float

    def _resolve_execution_workspace(self, execution_workspace: str | None) -> str: ...

    def _apply_execution_guardrails(
        self,
        *,
        execution_preset: str,
        tool_name: str,
        arguments: dict[str, Any],
        execution_workspace: str | None,
    ) -> tuple[dict[str, Any], str | None]: ...

    def _classify_guardrail_error_code(self, *, tool_name: str, error_text: str) -> str: ...

    def _normalize_agent_launch_arguments(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]: ...

    def _resolve_permission_gateway(self) -> Any: ...

    def _build_tool_span_id(self, turn_id: str, iteration: int, tool_call_id: str) -> str: ...

    async def _gate_tool_call(
        self,
        *,
        tool_call: ToolCall,
        tool_name: str,
        arguments: dict[str, Any],
        agent_id: str,
        session_id: str | None,
        turn_id: str | None,
        workspace: str | None,
        execution_preset: str,
        start_time: float,
        gateway: Any = None,
    ) -> ToolCallResult | None: ...

    def _resolve_scan_root_path(self, path_value: Any, execution_workspace: str | None) -> str: ...


@dataclass(slots=True)
class _RegisteredToolExecutionRequest:
    tool_call: ToolCall
    tool_name: str
    arguments: dict[str, Any]
    user_id: str
    session_id: str | None
    turn_id: str | None
    execution_preset: str
    execution_agent_id: str
    execution_workspace: str | None
    run_id: str
    run_revision: int
    reasoning_policy: ReasoningPolicy | None
    reasoning_state: ReasoningState | None
    user_message: str | None
    iteration: int | None
    start_time: float
    token: CancelToken
    workspace_root: str


@dataclass(slots=True)
class _SkillExecutionRequest:
    skill_name: str
    arguments: dict[str, Any]
    user_id: str
    execution_workspace: str | None
    session_id: str | None
    turn_id: str | None
    tool_call_id: str | None
    iteration: int | None


@dataclass(slots=True)
class _SkillTraceContext:
    trace_id: str | None
    parent_span_id: str | None
    args_list: list[str]
    args_summary: str | None
    started_at: float
    started_mono: float


@dataclass(slots=True)
class _SkillResultSnapshot:
    duration_ms: float
    finished_at: float
    success: bool
    content: Any
    error: Any
    result_summary: str | None
    fork_mode: bool
    allowed_tools: tuple[str, ...] | None


def _cancelled_tool_call_result(request: _RegisteredToolExecutionRequest) -> ToolCallResult:
    return ToolCallResult(
        tool_call_id=request.tool_call.id,
        tool_name=request.tool_name,
        success=False,
        error="Run cancelled before tool execution",
        error_code="CANCELLED",
        execution_time=time.time() - request.start_time,
    )


def _failed_tool_call_result(
    request: _RegisteredToolExecutionRequest,
    exc: Exception,
) -> ToolCallResult:
    return ToolCallResult(
        tool_call_id=request.tool_call.id,
        tool_name=request.tool_name,
        success=False,
        error=str(exc),
        execution_time=time.time() - request.start_time,
    )
