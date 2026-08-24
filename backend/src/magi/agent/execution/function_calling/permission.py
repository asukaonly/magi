"""Permission-gateway helpers for function-calling execution."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, cast

from magi.control.permission import PermissionOutcome, ToolOrigin

from ....tools.schema import ToolErrorCode
from .types import ToolCall, ToolCallResult

logger = logging.getLogger(__name__)


class _ToolRegistryProtocol(Protocol):
    def get_tool_info(self, tool_name: str) -> dict[str, Any] | None: ...


class _PermissionHostProtocol(Protocol):
    permission_gateway: Any
    _permission_gateway_provider: Callable[[], Any] | None
    tool_registry: _ToolRegistryProtocol


@dataclass(slots=True)
class _PermissionGateRequest:
    tool_call: ToolCall
    tool_name: str
    arguments: Dict[str, Any]
    agent_id: str
    session_id: Optional[str]
    turn_id: Optional[str]
    workspace: Optional[str]
    execution_preset: str
    start_time: float


class FunctionCallingPermissionMixin:
    """Resolve and apply control-plane permission gates for tool calls."""

    def _resolve_permission_gateway(self) -> Any:
        host = cast(_PermissionHostProtocol, self)
        if host.permission_gateway is not None:
            return host.permission_gateway
        if host._permission_gateway_provider is None:
            raise RuntimeError("Permission gateway is not configured")
        gateway = host._permission_gateway_provider()
        if gateway is None:
            raise RuntimeError("Permission gateway provider returned no gateway")
        return gateway

    async def _gate_tool_call(
        self,
        *,
        tool_call: ToolCall,
        tool_name: str,
        arguments: Dict[str, Any],
        agent_id: str,
        session_id: Optional[str],
        turn_id: Optional[str],
        workspace: Optional[str],
        execution_preset: str,
        start_time: float,
    ) -> Optional[ToolCallResult]:
        """Run the permission gateway; return a failure result if blocked."""
        host = cast(_PermissionHostProtocol, self)
        request = _PermissionGateRequest(
            tool_call=tool_call,
            tool_name=tool_name,
            arguments=arguments,
            agent_id=agent_id,
            session_id=session_id,
            turn_id=turn_id,
            workspace=workspace,
            execution_preset=execution_preset,
            start_time=start_time,
        )
        tool_info = host.tool_registry.get_tool_info(tool_name) or {}
        tool_metadata = tool_info.get("metadata") or {}

        try:
            gate = self._resolve_permission_gateway()
            decision = await gate.gate(
                tool_name=tool_name,
                arguments=arguments,
                agent_id=agent_id,
                origin=_tool_origin(execution_preset),
                session_id=session_id,
                turn_id=turn_id,
                workspace=workspace,
                tool_is_dangerous=bool(tool_info.get("dangerous", False)),
                tool_risk_level=tool_metadata.get("permission_risk"),
                tool_risk_authoritative=bool(
                    tool_metadata.get("permission_risk_authoritative", False)
                ),
                skill_preapproved=_is_skill_preapproved(tool_name, arguments),
            )
        except Exception as exc:
            logger.exception("[FunctionCalling] permission gateway raised")
            return _permission_error_result(request, exc)

        if decision.allowed:
            return None
        return _blocked_tool_result(request, decision)


def _tool_origin(execution_preset: str) -> ToolOrigin:
    if isinstance(execution_preset, str) and execution_preset.startswith("worker_"):
        return ToolOrigin.SUBAGENT
    if execution_preset.startswith("child_"):
        return ToolOrigin.SUBAGENT
    if execution_preset == "skill":
        return ToolOrigin.SKILL
    if execution_preset == "background":
        return ToolOrigin.BACKGROUND
    return ToolOrigin.CHAT


def _is_skill_preapproved(tool_name: str, arguments: Dict[str, Any]) -> bool:
    # A matching rule suppresses only the interactive prompt. The gateway still
    # applies system safety, plan mode, and effect policy first.
    try:
        from ....skills.active_restrictions import is_call_preapproved, matched_rule
    except Exception:
        return False
    if not is_call_preapproved(tool_name, arguments):
        return False

    rule = matched_rule(tool_name, arguments)
    logger.info(
        "[FunctionCalling] skill rule matched before permission gate tool=%s rule=%s",
        tool_name,
        rule.display if rule else "<unknown>",
    )
    return True


def _permission_error_result(
    request: _PermissionGateRequest,
    exc: Exception,
) -> ToolCallResult:
    return ToolCallResult(
        tool_call_id=request.tool_call.id,
        tool_name=request.tool_name,
        success=False,
        error=f"permission gateway error: {exc}",
        error_code=ToolErrorCode.PERMISSION_DENIED.value,
        execution_time=time.time() - request.start_time,
    )


def _blocked_tool_result(
    request: _PermissionGateRequest,
    decision: Any,
) -> ToolCallResult:
    logger.info(
        "[FunctionCalling] permission blocked tool=%s outcome=%s source=%s",
        request.tool_name,
        decision.outcome.value,
        decision.source,
    )
    return ToolCallResult(
        tool_call_id=request.tool_call.id,
        tool_name=request.tool_name,
        success=False,
        error=_blocked_tool_message(decision),
        error_code=ToolErrorCode.PERMISSION_DENIED.value,
        execution_time=time.time() - request.start_time,
    )


def _blocked_tool_message(decision: Any) -> str:
    if decision.outcome is PermissionOutcome.KILL_LISTED:
        return (
            f"This invocation is blocked by the system safety fuse: "
            f"{decision.reason or 'kill-listed pattern'}. Rephrase your "
            f"approach -- do not retry this exact command."
        )
    if decision.outcome is PermissionOutcome.TIMED_OUT:
        return (
            "The user did not respond to the permission prompt in time; "
            "the call was not executed. Ask the user how they want to proceed."
        )
    if decision.outcome is PermissionOutcome.DENIED:
        return _denied_tool_message(decision)
    return f"permission gateway blocked the call ({decision.outcome.value})"


def _denied_tool_message(decision: Any) -> str:
    if decision.source == "plan_mode":
        return decision.reason or "plan mode is active: only read-only tools are allowed"
    return (
        "The user denied this tool invocation"
        + (f": {decision.reason}" if decision.reason else "")
        + ". Respect the decision and choose a different approach."
    )
