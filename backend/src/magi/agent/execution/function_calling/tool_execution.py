"""Tool and skill execution helpers for function-calling orchestration."""

from __future__ import annotations

import logging
import time
from typing import Any, cast

from ...cancel import CancelToken, null_cancel_token
from ._registered_tool_execution import _RegisteredToolExecutor
from ._skill_tool_execution import _SkillToolExecutor
from ._tool_execution_contracts import (
    _FunctionCallingToolExecutionHostProtocol,
    _RegisteredToolExecutionRequest,
    _SkillExecutionRequest,
    _cancelled_tool_call_result,
    _failed_tool_call_result,
)
from .types import ToolCall, ToolCallResult
from magi.skills.allowed_tools_rules import ToolRule

logger = logging.getLogger(__name__)


_MEMORY_QUERY_CONTEXT_TURNS = 4


def _coerce_message_text(content: Any) -> str:
    """Best-effort flatten LLM message content into a plain string.

    Conversation history may carry either ``str`` content or a list of
    structured blocks (text / image). The indexical resolver only needs
    the textual portion so we join text blocks and drop the rest.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if str(block.get("type") or "").strip() != "text":
                continue
            text_value = str(block.get("text") or "").strip()
            if text_value:
                parts.append(text_value)
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _inject_memory_query_context(
    tool_name: str,
    parameters: dict[str, Any],
    recent_messages: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Auto-inject ``conversation_context`` for ``memory_query`` when missing.

    Phase 3 indexical resolver: queries like ``"当时我说什么"`` need the last
    few conversation turns to anchor ``"当时"`` / ``"just now"`` references.
    The chat LLM does not reliably populate ``conversation_context`` (it
    tends to paraphrase the user query instead), so the dispatcher silently
    injects the last :data:`_MEMORY_QUERY_CONTEXT_TURNS` turns from the live
    chat session history before ``Tool.execute`` is invoked.

    Round 5 I5: the current user turn (the one that triggered this tool
    call) is excluded — it IS the indexical query and would be a no-op for
    resolution. The slice walks back from the most recent user message,
    grabbing only PRIOR turns.

    Returns a new ``parameters`` dict — the input is never mutated.
    """
    if tool_name != "memory_query":
        return parameters
    if parameters.get("conversation_context"):
        return parameters
    if not recent_messages:
        return parameters

    # Find the most recent user message (the current turn) and exclude it
    # plus anything after it (assistant tool-call response, etc.).
    cutoff = len(recent_messages)
    for idx in range(len(recent_messages) - 1, -1, -1):
        msg = recent_messages[idx]
        if isinstance(msg, dict) and str(msg.get("role") or "").strip() == "user":
            cutoff = idx
            break

    prior = recent_messages[:cutoff]
    last_n = prior[-_MEMORY_QUERY_CONTEXT_TURNS:]
    enriched_turns: list[dict[str, Any]] = []
    for msg in last_n:
        if not isinstance(msg, dict):
            continue
        text = _coerce_message_text(msg.get("content"))
        if not text:
            continue
        role = str(msg.get("role") or "user").strip() or "user"
        timestamp_raw = msg.get("timestamp", 0.0)
        try:
            timestamp_value = float(timestamp_raw)
        except (TypeError, ValueError):
            timestamp_value = 0.0
        enriched_turns.append(
            {
                "role": role,
                "content": text,
                "timestamp": timestamp_value,
            }
        )

    if not enriched_turns:
        return parameters

    enriched = dict(parameters)
    enriched["conversation_context"] = enriched_turns
    return enriched


def _build_registered_tool_execution_request(
    *,
    tool_call: ToolCall,
    tool_name: str,
    arguments: dict[str, Any],
    user_id: str,
    session_id: str | None,
    turn_id: str | None,
    execution_preset: str,
    execution_agent_id: str,
    execution_workspace: str | None,
    run_id: str,
    run_revision: int,
    reasoning_policy: Any = None,
    reasoning_state: Any = None,
    user_message: str | None,
    iteration: int | None,
    start_time: float,
    token: CancelToken,
    workspace_root: str,
    skill_preapproval_rules: tuple[ToolRule, ...],
) -> _RegisteredToolExecutionRequest:
    return _RegisteredToolExecutionRequest(
        tool_call=tool_call,
        tool_name=tool_name,
        arguments=arguments,
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
        execution_preset=execution_preset,
        execution_agent_id=execution_agent_id,
        execution_workspace=execution_workspace,
        run_id=run_id,
        run_revision=run_revision,
        reasoning_policy=reasoning_policy,
        reasoning_state=reasoning_state,
        user_message=user_message,
        iteration=iteration,
        start_time=start_time,
        token=token,
        workspace_root=workspace_root,
        skill_preapproval_rules=skill_preapproval_rules,
    )


def _prepare_registered_tool_execution_request(
    *,
    host: _FunctionCallingToolExecutionHostProtocol,
    tool_call: ToolCall,
    user_id: str,
    session_id: str | None,
    turn_id: str | None,
    execution_preset: str,
    execution_agent_id: str,
    execution_workspace: str | None,
    run_id: str,
    run_revision: int,
    reasoning_policy: Any = None,
    reasoning_state: Any = None,
    user_message: str | None,
    iteration: int | None,
    cancel_token: CancelToken | None,
    recent_messages: list[dict[str, Any]] | None,
    skill_preapproval_rules: tuple[ToolRule, ...],
) -> _RegisteredToolExecutionRequest:
    start_time = time.time()
    token = cancel_token if cancel_token is not None else null_cancel_token()
    tool_name = tool_call.name
    arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
    arguments = _inject_memory_query_context(tool_name, arguments, recent_messages)
    return _build_registered_tool_execution_request(
        tool_call=tool_call,
        tool_name=tool_name,
        arguments=arguments,
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
        execution_preset=execution_preset,
        execution_agent_id=execution_agent_id,
        execution_workspace=execution_workspace,
        run_id=run_id,
        run_revision=run_revision,
        reasoning_policy=reasoning_policy,
        reasoning_state=reasoning_state,
        user_message=user_message,
        iteration=iteration,
        start_time=start_time,
        token=token,
        workspace_root=host._resolve_execution_workspace(execution_workspace),
        skill_preapproval_rules=skill_preapproval_rules,
    )


class FunctionCallingToolExecutionMixin:
    """Execute concrete tool calls and skill-backed tools."""

    async def _execute_tool_call(
        self,
        tool_call: ToolCall,
        user_id: str,
        session_id: str | None,
        turn_id: str | None,
        execution_preset: str,
        execution_agent_id: str,
        execution_workspace: str | None,
        run_id: str,
        run_revision: int = 0,
        reasoning_policy: Any = None,
        reasoning_state: Any = None,
        user_message: str | None = None,
        iteration: int | None = None,
        cancel_token: CancelToken | None = None,
        recent_messages: list[dict[str, Any]] | None = None,
        skill_preapproval_rules: tuple[ToolRule, ...] = (),
    ) -> ToolCallResult:
        """Execute a single tool call."""
        host = cast(_FunctionCallingToolExecutionHostProtocol, self)
        request = _prepare_registered_tool_execution_request(
            host=host,
            tool_call=tool_call,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            execution_preset=execution_preset,
            execution_agent_id=execution_agent_id,
            execution_workspace=execution_workspace,
            run_id=run_id,
            run_revision=run_revision,
            reasoning_policy=reasoning_policy,
            reasoning_state=reasoning_state,
            user_message=user_message,
            iteration=iteration,
            cancel_token=cancel_token,
            recent_messages=recent_messages,
            skill_preapproval_rules=skill_preapproval_rules,
        )

        if await request.token.is_cancelled():
            return _cancelled_tool_call_result(request)

        try:
            skill_result = await self._try_execute_skill_tool(request)
            if skill_result is not None:
                return skill_result

            role_result = self._reject_worker_owned_tool(request)
            if role_result is not None:
                return role_result

            return await _RegisteredToolExecutor(host).execute(request)

        except Exception as exc:
            logger.error("[FunctionCalling] Tool execution error: %s", exc)
            return _failed_tool_call_result(request, exc)

    async def _try_execute_skill_tool(
        self,
        request: _RegisteredToolExecutionRequest,
    ) -> ToolCallResult | None:
        if not request.tool_name.startswith("skill_"):
            return None
        skill_name = request.tool_name.replace("skill_", "")
        return await self._execute_skill(
            skill_name=skill_name,
            arguments=request.arguments,
            user_id=request.user_id,
            execution_workspace=request.execution_workspace,
            session_id=request.session_id,
            turn_id=request.turn_id,
            tool_call_id=request.tool_call.id,
            iteration=request.iteration,
        )

    def _reject_worker_owned_tool(
        self,
        request: _RegisteredToolExecutionRequest,
    ) -> ToolCallResult | None:
        if request.tool_name != "todo_write":
            return None
        if not (
            str(request.execution_preset or "").startswith("worker_")
            or str(request.execution_agent_id or "").startswith("worker_")
        ):
            return None
        return ToolCallResult(
            tool_call_id=request.tool_call.id,
            tool_name=request.tool_name,
            success=False,
            error=(
                "todo_write is owned by the parent task agent; "
                "worker agents must report progress through worker results."
            ),
            error_code="ROLE_NOT_ALLOWED",
            execution_time=time.time() - request.start_time,
        )

    async def _execute_skill(
        self,
        skill_name: str,
        arguments: dict[str, Any],
        user_id: str,
        execution_workspace: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        tool_call_id: str | None = None,
        iteration: int | None = None,
    ) -> ToolCallResult:
        """Execute a skill-backed tool call.

        Wraps execution in a ``skill_call`` span so the call appears in the
        trace chain alongside tool invocations, and publishes a
        ``SkillInvocationCompleted`` event for memory ingestion.
        """
        host = cast(_FunctionCallingToolExecutionHostProtocol, self)
        return await _SkillToolExecutor(host=host).execute(
            _SkillExecutionRequest(
                skill_name=skill_name,
                arguments=arguments,
                user_id=user_id,
                execution_workspace=execution_workspace,
                session_id=session_id,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                iteration=iteration,
            )
        )


__all__ = ["FunctionCallingToolExecutionMixin"]
