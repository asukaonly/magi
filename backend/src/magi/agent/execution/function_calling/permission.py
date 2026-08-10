"""Permission-gateway helpers for function-calling execution."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, cast

from .types import ToolCall, ToolCallResult

logger = logging.getLogger(__name__)


class _ToolRegistryProtocol(Protocol):
    def get_tool_info(self, tool_name: str) -> dict[str, Any] | None: ...


class _PermissionHostProtocol(Protocol):
    permission_gateway: Any
    _permission_gateway_provider: Callable[[], Any] | None
    tool_registry: _ToolRegistryProtocol


@dataclass(slots=True)
class _PermissionGateImports:
    permission_outcome: Any
    tool_origin: Any
    tool_error_code: Any


@dataclass(slots=True)
class _PermissionGateRequest:
    tool_call: ToolCall
    tool_name: str
    arguments: Dict[str, Any]
    agent_id: str
    session_id: Optional[str]
    turn_id: Optional[str]
    workspace: Optional[str]
    intent: str
    start_time: float


class FunctionCallingPermissionMixin:
    """Resolve and apply control-plane permission gates for tool calls."""

    def _resolve_permission_gateway(self) -> Any:
        host = cast(_PermissionHostProtocol, self)
        if host.permission_gateway is not None:
            return host.permission_gateway
        if host._permission_gateway_provider is None:
            return None
        try:
            return host._permission_gateway_provider()
        except Exception:
            return None

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
        intent: str,
        start_time: float,
        gateway: Any = None,
    ) -> Optional[ToolCallResult]:
        """Run the permission gateway; return a failure result if blocked."""
        imports = _load_permission_gate_imports()
        if imports is None:
            return None

        host = cast(_PermissionHostProtocol, self)
        request = _PermissionGateRequest(
            tool_call=tool_call,
            tool_name=tool_name,
            arguments=arguments,
            agent_id=agent_id,
            session_id=session_id,
            turn_id=turn_id,
            workspace=workspace,
            intent=intent,
            start_time=start_time,
        )
        tool_info = host.tool_registry.get_tool_info(tool_name) or {}
        tool_metadata = tool_info.get("metadata") or {}

        if _is_skill_preapproved(tool_name, arguments):
            return None

        try:
            gate = gateway if gateway is not None else self._resolve_permission_gateway()
            if gate is None:
                return None
            decision = await gate.gate(
                tool_name=tool_name,
                arguments=arguments,
                agent_id=agent_id,
                origin=_tool_origin(imports, intent),
                session_id=session_id,
                turn_id=turn_id,
                workspace=workspace,
                tool_is_dangerous=bool(tool_info.get("dangerous", False)),
                tool_risk_level=tool_metadata.get("permission_risk"),
                tool_risk_authoritative=bool(
                    tool_metadata.get("permission_risk_authoritative", False)
                ),
            )
        except Exception as exc:
            logger.exception("[FunctionCalling] permission gateway raised")
            return _permission_error_result(request, imports, exc)

        if decision.allowed:
            return None
        return _blocked_tool_result(request, imports, decision)


def _load_permission_gate_imports() -> _PermissionGateImports | None:
    try:
        from magi.control.permission import PermissionOutcome, ToolOrigin
        from ....tools.schema import ToolErrorCode
    except Exception as exc:  # defensive -- should never fire post-wiring
        logger.error(f"[FunctionCalling] permission gateway import failed: {exc}")
        return None
    return _PermissionGateImports(
        permission_outcome=PermissionOutcome,
        tool_origin=ToolOrigin,
        tool_error_code=ToolErrorCode,
    )


def _tool_origin(imports: _PermissionGateImports, intent: str) -> Any:
    if isinstance(intent, str) and intent.startswith("worker_"):
        return imports.tool_origin.SUBAGENT
    return imports.tool_origin.CHAT


def _is_skill_preapproved(tool_name: str, arguments: Dict[str, Any]) -> bool:
    # Claude Code spec: a skill's ``allowed-tools`` field pre-approves matching
    # tool calls. Matching calls skip prompts, kill-list checks, and cached rules.
    try:
        from ....skills.active_restrictions import is_call_preapproved, matched_rule
    except Exception:
        return False
    if not is_call_preapproved(tool_name, arguments):
        return False

    rule = matched_rule(tool_name, arguments)
    logger.info(
        "[FunctionCalling] permission skipped by skill pre-approval tool=%s rule=%s",
        tool_name,
        rule.display if rule else "<unknown>",
    )
    return True


def _permission_error_result(
    request: _PermissionGateRequest,
    imports: _PermissionGateImports,
    exc: Exception,
) -> ToolCallResult:
    return ToolCallResult(
        tool_call_id=request.tool_call.id,
        tool_name=request.tool_name,
        success=False,
        error=f"permission gateway error: {exc}",
        error_code=imports.tool_error_code.PERMISSION_DENIED.value,
        execution_time=time.time() - request.start_time,
    )


def _blocked_tool_result(
    request: _PermissionGateRequest,
    imports: _PermissionGateImports,
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
        error=_blocked_tool_message(imports, decision),
        error_code=imports.tool_error_code.PERMISSION_DENIED.value,
        execution_time=time.time() - request.start_time,
    )


def _blocked_tool_message(imports: _PermissionGateImports, decision: Any) -> str:
    outcome = imports.permission_outcome
    if decision.outcome is outcome.KILL_LISTED:
        return (
            f"This invocation is blocked by the system safety fuse: "
            f"{decision.reason or 'kill-listed pattern'}. Rephrase your "
            f"approach -- do not retry this exact command."
        )
    if decision.outcome is outcome.TIMED_OUT:
        return (
            "The user did not respond to the permission prompt in time; "
            "the call was not executed. Ask the user how they want to proceed."
        )
    if decision.outcome is outcome.DENIED:
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
