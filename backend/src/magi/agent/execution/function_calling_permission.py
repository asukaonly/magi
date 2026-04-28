"""Permission-gateway helpers for function-calling execution."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from .function_calling_types import ToolCall, ToolCallResult

logger = logging.getLogger(__name__)


class FunctionCallingPermissionMixin:
    """Resolve and apply control-plane permission gates for tool calls."""

    def _resolve_permission_gateway(self) -> Any:
        if self.permission_gateway is not None:
            return self.permission_gateway
        if self._permission_gateway_provider is None:
            return None
        try:
            return self._permission_gateway_provider()
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
        try:
            from ..control.permission import (
                PermissionOutcome,
                ToolOrigin,
            )
            from ...tools.schema import ToolErrorCode
        except Exception as exc:  # defensive -- should never fire post-wiring
            logger.error(f"[FunctionCalling] permission gateway import failed: {exc}")
            return None

        tool_info = self.tool_registry.get_tool_info(tool_name) or {}
        origin = (
            ToolOrigin.SUBAGENT
            if isinstance(intent, str) and intent.startswith("worker_")
            else ToolOrigin.CHAT
        )

        try:
            gate = gateway if gateway is not None else self._resolve_permission_gateway()
            if gate is None:
                return None
            decision = await gate.gate(
                tool_name=tool_name,
                arguments=arguments,
                agent_id=agent_id,
                origin=origin,
                session_id=session_id,
                turn_id=turn_id,
                workspace=workspace,
                tool_is_dangerous=bool(tool_info.get("dangerous", False)),
            )
        except Exception as exc:
            logger.exception("[FunctionCalling] permission gateway raised")
            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                error=f"permission gateway error: {exc}",
                error_code=ToolErrorCode.PERMISSION_DENIED.value,
                execution_time=time.time() - start_time,
            )

        if decision.allowed:
            return None

        if decision.outcome is PermissionOutcome.KILL_LISTED:
            message = (
                f"This invocation is blocked by the system safety fuse: "
                f"{decision.reason or 'kill-listed pattern'}. Rephrase your "
                f"approach -- do not retry this exact command."
            )
        elif decision.outcome is PermissionOutcome.TIMED_OUT:
            message = (
                "The user did not respond to the permission prompt in time; "
                "the call was not executed. Ask the user how they want to proceed."
            )
        elif decision.outcome is PermissionOutcome.DENIED:
            if decision.source == "plan_mode":
                message = (
                    decision.reason
                    or "plan mode is active: only read-only tools are allowed"
                )
            else:
                message = (
                    f"The user denied this tool invocation"
                    + (f": {decision.reason}" if decision.reason else "")
                    + ". Respect the decision and choose a different approach."
                )
        else:
            message = f"permission gateway blocked the call ({decision.outcome.value})"

        logger.info(
            "[FunctionCalling] permission blocked tool=%s outcome=%s source=%s",
            tool_name,
            decision.outcome.value,
            decision.source,
        )
        return ToolCallResult(
            tool_call_id=tool_call.id,
            tool_name=tool_name,
            success=False,
            error=message,
            error_code=ToolErrorCode.PERMISSION_DENIED.value,
            execution_time=time.time() - start_time,
        )