"""Run user-invocable commands and persist them in the chat timeline.

Each invocation produces two transcript messages:

1. A ``user`` message with ``message_kind="command_invocation"`` carrying the
   original ``/cmd k=v`` text in ``content_text`` and the parsed call shape
   (tool name, arguments) in ``payload_json["command"]``.
2. A ``message_kind="command_result"`` message with the tool output in
   ``content_text`` and metadata in ``payload_json["command_result"]``
   (success, error_code, execution_time, invoked_command).

Permission gating reuses ``PermissionGateway`` — same path the LLM-driven
calls use. ``dangerous=true`` tools still go through ``brokered_prompter``.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from magi_plugin_sdk.tools import (
    ToolErrorCode,
    ToolExecutionContext,
    ToolResult,
)

from ..control.permission.contracts import (
    PermissionDecision,
    PermissionOutcome,
    PermissionRequest,
    ToolOrigin,
)
from ..core.runtime_bindings import require_chat_surface_write_service
from ..tools.capabilities import build_tool_capabilities
from ..tools.registry import ToolRegistry
from .resolver import UserInvocableResolver, get_default_resolver

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CommandRunResult:
    success: bool
    message_id: str
    invocation_message_id: str
    output_text: str
    error: str | None = None
    error_code: str | None = None
    execution_time_ms: int = 0


@dataclass(frozen=True, slots=True)
class _CommandCall:
    user_id: str
    session_id: str
    tool_name: str
    arguments: dict[str, Any]
    invocation_text: str
    agent_id: str
    workspace: str | None
    turn_id: str
    invocation_message_id: str


class CommandTranscriptWriter(Protocol):
    async def append_command_invocation(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        invocation_text: str,
    ) -> str: ...

    async def append_command_result(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        invocation_message_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        output_text: str,
        success: bool,
        error: str | None,
        error_code: str | None,
        execution_time_ms: int,
        invocation_text: str | None = None,
    ) -> str: ...


class CommandRunner:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        resolver: UserInvocableResolver | None = None,
        permission_gateway_provider: Callable[[], Any] | None = None,
        transcript_writer: CommandTranscriptWriter | None = None,
    ) -> None:
        self._registry = registry
        self._resolver = resolver or get_default_resolver()
        self._permission_gateway_provider = permission_gateway_provider
        self._transcript_writer = transcript_writer

    async def run_tool_command(
        self,
        *,
        user_id: str,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        invocation_text: str,
        agent_id: str | None = None,
        workspace: str | None = None,
    ) -> CommandRunResult:
        preflight_failure = await self._preflight_tool_command(
            user_id=user_id,
            session_id=session_id,
            tool_name=tool_name,
            arguments=arguments,
            invocation_text=invocation_text,
        )
        if preflight_failure is not None:
            return preflight_failure

        turn_id = f"cmd_{uuid.uuid4().hex[:16]}"
        invocation_message_id = await self._append_invocation_message(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            tool_name=tool_name,
            arguments=arguments,
            invocation_text=invocation_text,
        )
        call = _CommandCall(
            user_id=user_id,
            session_id=session_id,
            tool_name=tool_name,
            arguments=arguments,
            invocation_text=invocation_text,
            agent_id=agent_id or user_id,
            workspace=workspace,
            turn_id=turn_id,
            invocation_message_id=invocation_message_id,
        )

        gateway_decision = await self._gate(
            tool_name=tool_name,
            arguments=arguments,
            agent_id=call.agent_id,
            session_id=session_id,
            turn_id=turn_id,
            workspace=workspace,
        )
        blocked_result = await self._blocked_permission_result(call, gateway_decision)
        if blocked_result is not None:
            return blocked_result

        ctx = self._execution_context(call)
        return await self._execute_and_record(call, ctx)

    async def _preflight_tool_command(
        self,
        *,
        user_id: str,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        invocation_text: str,
    ) -> CommandRunResult | None:
        if not self._resolver.is_user_invocable(self._registry, tool_name):
            return await self._record_failure(
                user_id=user_id,
                session_id=session_id,
                tool_name=tool_name,
                arguments=arguments,
                invocation_text=invocation_text,
                error=f"Tool {tool_name!r} is not user-invocable.",
                error_code=ToolErrorCode.PERMISSION_DENIED.value,
            )
        if self._registry.get_tool(tool_name) is None:
            return await self._record_failure(
                user_id=user_id,
                session_id=session_id,
                tool_name=tool_name,
                arguments=arguments,
                invocation_text=invocation_text,
                error=f"Tool {tool_name!r} not found.",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
            )
        return None

    async def _blocked_permission_result(
        self,
        call: _CommandCall,
        gateway_decision: Any,
    ) -> CommandRunResult | None:
        if gateway_decision is None or gateway_decision.allowed:
            return None
        return await self._append_call_result(
            call,
            output_text=gateway_decision.reason or "Permission denied.",
            success=False,
            error=gateway_decision.reason,
            error_code=ToolErrorCode.PERMISSION_DENIED.value,
            execution_time_ms=0,
        )

    def _execution_context(
        self,
        call: _CommandCall,
    ) -> ToolExecutionContext:
        return ToolExecutionContext(
            agent_id=call.agent_id,
            task_id=call.turn_id,
            workspace=call.workspace or "",
            env_vars={"role": "user"},
            permissions=["authenticated", "dangerous_tools"],
            enabled_features=[],
            capabilities=build_tool_capabilities(),
        )

    async def _execute_and_record(
        self,
        call: _CommandCall,
        ctx: ToolExecutionContext,
    ) -> CommandRunResult:
        started = time.monotonic()
        try:
            result: ToolResult = await self._registry.execute(
                call.tool_name,
                call.arguments,
                ctx,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Command execution raised: %s", call.tool_name)
            return await self._append_call_result(
                call,
                output_text=str(exc),
                success=False,
                error=str(exc),
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
                execution_time_ms=int((time.monotonic() - started) * 1000),
            )
        execution_time_ms = int((time.monotonic() - started) * 1000)
        return await self._append_call_result(
            call,
            output_text=_extract_text(result),
            success=result.success,
            error=result.error,
            error_code=result.error_code,
            execution_time_ms=execution_time_ms,
        )

    async def _append_call_result(
        self,
        call: _CommandCall,
        *,
        output_text: str,
        success: bool,
        error: str | None,
        error_code: str | None,
        execution_time_ms: int,
    ) -> CommandRunResult:
        return await self._append_result_message(
            user_id=call.user_id,
            session_id=call.session_id,
            turn_id=call.turn_id,
            invocation_message_id=call.invocation_message_id,
            tool_name=call.tool_name,
            arguments=call.arguments,
            output_text=output_text,
            success=success,
            error=error,
            error_code=error_code,
            execution_time_ms=execution_time_ms,
        )

    async def _gate(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        agent_id: str,
        session_id: str,
        turn_id: str,
        workspace: str | None,
    ):
        if self._permission_gateway_provider is None:
            return _gateway_unavailable_decision("permission gateway is not configured")
        try:
            gateway = self._permission_gateway_provider()
        except Exception as exc:
            logger.exception("Command permission gateway provider failed")
            return _gateway_unavailable_decision(f"permission gateway provider failed: {exc}")
        if gateway is None:
            return _gateway_unavailable_decision("permission gateway provider returned no gateway")
        info = self._registry.get_tool_info(tool_name) or {}
        metadata = info.get("metadata") or {}
        try:
            return await gateway.gate(
                tool_name=tool_name,
                arguments=arguments,
                agent_id=agent_id,
                origin=ToolOrigin.CHAT,
                session_id=session_id,
                turn_id=turn_id,
                workspace=workspace,
                tool_is_dangerous=bool(info.get("dangerous", False)),
                tool_risk_level=metadata.get("permission_risk"),
                tool_risk_authoritative=bool(
                    metadata.get("permission_risk_authoritative", False)
                ),
            )
        except Exception as exc:
            logger.exception("Command permission gateway failed")
            return _gateway_unavailable_decision(f"permission gateway failed: {exc}")

    async def _append_invocation_message(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        invocation_text: str,
    ) -> str:
        return await self._writer().append_command_invocation(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            tool_name=tool_name,
            arguments=arguments,
            invocation_text=invocation_text,
        )

    async def _append_result_message(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        invocation_message_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        output_text: str,
        success: bool,
        error: str | None,
        error_code: str | None,
        execution_time_ms: int,
        invocation_text: str | None = None,
    ) -> CommandRunResult:
        message_id = await self._writer().append_command_result(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            invocation_message_id=invocation_message_id,
            tool_name=tool_name,
            arguments=arguments,
            output_text=output_text,
            success=success,
            error=error,
            error_code=error_code,
            execution_time_ms=execution_time_ms,
            invocation_text=invocation_text,
        )
        return CommandRunResult(
            success=success,
            message_id=message_id,
            invocation_message_id=invocation_message_id,
            output_text=output_text,
            error=error,
            error_code=error_code,
            execution_time_ms=execution_time_ms,
        )

    async def _record_failure(
        self,
        *,
        user_id: str,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        invocation_text: str,
        error: str,
        error_code: str,
    ) -> CommandRunResult:
        # Failure cases write only the result message (no invocation row,
        # because tool wasn't actually started). The frontend chip can still
        # show the attempted call from payload_json.
        turn_id = f"cmd_{uuid.uuid4().hex[:16]}"
        return await self._append_result_message(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            invocation_message_id="",
            tool_name=tool_name,
            arguments=arguments,
            output_text=error,
            success=False,
            error=error,
            error_code=error_code,
            execution_time_ms=0,
            invocation_text=invocation_text,
        )

    def _writer(self) -> CommandTranscriptWriter:
        if self._transcript_writer is None:
            self._transcript_writer = require_chat_surface_write_service()
        return self._transcript_writer


def _extract_text(result: ToolResult) -> str:
    if result is None:
        return ""
    if not result.success and result.error:
        return result.error
    data = getattr(result, "data", None)
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        # Common Magi pattern: data["output"] or data["text"].
        for key in ("output", "text", "content"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        try:
            return json.dumps(data, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(data)
    if isinstance(data, list):
        try:
            return json.dumps(data, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(data)
    metadata_output = (result.metadata or {}).get("output")
    if isinstance(metadata_output, str) and metadata_output:
        return metadata_output
    return ""


def _gateway_unavailable_decision(reason: str) -> PermissionDecision:
    return PermissionDecision(
        request_id=PermissionRequest.new_id(),
        outcome=PermissionOutcome.DENIED,
        source="gateway_unavailable",
        reason=reason,
    )
