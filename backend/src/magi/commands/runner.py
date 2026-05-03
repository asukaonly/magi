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
from typing import Any, Callable

from magi_plugin_sdk.tools import (
    ToolErrorCode,
    ToolExecutionContext,
    ToolResult,
)

from ..agent.control.permission.contracts import ToolOrigin
from ..chat.contracts import ChatMessageRecord
from ..chat.provider import get_chat_store
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


class CommandRunner:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        resolver: UserInvocableResolver | None = None,
        permission_gateway_provider: Callable[[], Any] | None = None,
        notifier: Callable[[str, str, str], Any] | None = None,
    ) -> None:
        self._registry = registry
        self._resolver = resolver or get_default_resolver()
        self._permission_gateway_provider = permission_gateway_provider
        self._notifier = notifier

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

        tool = self._registry.get_tool(tool_name)
        if tool is None:
            return await self._record_failure(
                user_id=user_id,
                session_id=session_id,
                tool_name=tool_name,
                arguments=arguments,
                invocation_text=invocation_text,
                error=f"Tool {tool_name!r} not found.",
                error_code=ToolErrorCode.TOOL_NOT_FOUND.value,
            )

        turn_id = f"cmd_{uuid.uuid4().hex[:16]}"
        invocation_msg = await self._append_invocation_message(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            tool_name=tool_name,
            arguments=arguments,
            invocation_text=invocation_text,
        )

        gateway_decision = await self._gate(
            tool_name=tool_name,
            arguments=arguments,
            agent_id=agent_id or user_id,
            session_id=session_id,
            turn_id=turn_id,
            workspace=workspace,
        )
        if gateway_decision is not None and not gateway_decision.allowed:
            return await self._append_result_message(
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                invocation_message_id=invocation_msg.message_id,
                tool_name=tool_name,
                arguments=arguments,
                output_text=gateway_decision.reason or "Permission denied.",
                success=False,
                error=gateway_decision.reason,
                error_code=ToolErrorCode.PERMISSION_DENIED.value,
                execution_time_ms=0,
            )

        # Build a synthetic execution context. ``dangerous_tools`` permission
        # is granted because the user-invocable contract demands explicit
        # opt-in (metadata or whitelist) and the gateway has already
        # adjudicated dangerous-ness above.
        ctx = ToolExecutionContext(
            agent_id=agent_id or user_id,
            task_id=turn_id,
            workspace=workspace or "",
            env_vars={"role": "user"},
            permissions=["dangerous_tools"],
            enabled_features=[],
        )

        started = time.monotonic()
        try:
            result: ToolResult = await self._registry.execute(tool_name, arguments, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Command execution raised: %s", tool_name)
            return await self._append_result_message(
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                invocation_message_id=invocation_msg.message_id,
                tool_name=tool_name,
                arguments=arguments,
                output_text=str(exc),
                success=False,
                error=str(exc),
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
                execution_time_ms=int((time.monotonic() - started) * 1000),
            )
        execution_time_ms = int((time.monotonic() - started) * 1000)

        output_text = _extract_text(result)
        return await self._append_result_message(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            invocation_message_id=invocation_msg.message_id,
            tool_name=tool_name,
            arguments=arguments,
            output_text=output_text,
            success=result.success,
            error=result.error,
            error_code=result.error_code,
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
            return None
        try:
            gateway = self._permission_gateway_provider()
        except RuntimeError:
            return None
        if gateway is None:
            return None
        info = self._registry.get_tool_info(tool_name) or {}
        return await gateway.gate(
            tool_name=tool_name,
            arguments=arguments,
            agent_id=agent_id,
            origin=ToolOrigin.CHAT,
            session_id=session_id,
            turn_id=turn_id,
            workspace=workspace,
            tool_is_dangerous=bool(info.get("dangerous", False)),
        )

    async def _append_invocation_message(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        invocation_text: str,
    ) -> ChatMessageRecord:
        store = get_chat_store()
        now_ms = int(time.time() * 1000)
        payload = {
            "command": {
                "tool_name": tool_name,
                "arguments": arguments,
            }
        }
        record = ChatMessageRecord(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_id,
            role="user",
            message_kind="command_invocation",
            content_text=invocation_text or f"/{tool_name}",
            payload_json=json.dumps(payload, ensure_ascii=False),
            is_final=True,
            is_visible=True,
            created_at_ms=now_ms,
            sequence_no=1,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
        await store.append_message(record)
        await self._notify(user_id, session_id, record.message_id)
        return record

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
    ) -> CommandRunResult:
        store = get_chat_store()
        now_ms = int(time.time() * 1000)
        payload = {
            "command_result": {
                "tool_name": tool_name,
                "arguments": arguments,
                "success": success,
                "error": error,
                "error_code": error_code,
                "execution_time_ms": execution_time_ms,
                "invocation_message_id": invocation_message_id,
            }
        }
        record = ChatMessageRecord(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_id,
            role="tool",
            message_kind="command_result",
            content_text=output_text,
            payload_json=json.dumps(payload, ensure_ascii=False),
            is_final=True,
            is_visible=True,
            created_at_ms=now_ms,
            sequence_no=2,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
        await store.append_message(record)
        await self._notify(user_id, session_id, record.message_id)
        return CommandRunResult(
            success=success,
            message_id=record.message_id,
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
        store = get_chat_store()
        now_ms = int(time.time() * 1000)
        payload = {
            "command_result": {
                "tool_name": tool_name,
                "arguments": arguments,
                "success": False,
                "error": error,
                "error_code": error_code,
                "execution_time_ms": 0,
                "invocation_text": invocation_text,
            }
        }
        record = ChatMessageRecord(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_id,
            role="tool",
            message_kind="command_result",
            content_text=error,
            payload_json=json.dumps(payload, ensure_ascii=False),
            is_final=True,
            is_visible=True,
            created_at_ms=now_ms,
            sequence_no=1,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
        await store.append_message(record)
        await self._notify(user_id, session_id, record.message_id)
        return CommandRunResult(
            success=False,
            message_id=record.message_id,
            invocation_message_id="",
            output_text=error,
            error=error,
            error_code=error_code,
        )

    async def _notify(self, user_id: str, session_id: str, message_id: str) -> None:
        if self._notifier is None:
            return
        try:
            maybe = self._notifier(user_id, session_id, message_id)
            if hasattr(maybe, "__await__"):
                await maybe
        except Exception:
            logger.exception("command_runner: notifier raised")


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
