"""Tool and skill execution helpers for function-calling orchestration."""

from __future__ import annotations

import getpass
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Protocol, cast

from ...cancel import CancelToken, null_cancel_token
from .types import ToolCall, ToolCallResult
from magi.tools.capabilities import build_tool_capabilities

if TYPE_CHECKING:
    from ....tools.context_routing import RouteDecision

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

    def _apply_worker_explore_guardrails(
        self,
        *,
        intent: str,
        tool_name: str,
        arguments: dict[str, Any],
        execution_workspace: str | None,
    ) -> tuple[dict[str, Any], str | None]: ...

    def _classify_guardrail_error_code(self, *, tool_name: str, error_text: str) -> str: ...

    def _normalize_agent_launch_arguments(
        self,
        arguments: dict[str, Any],
        orchestration_strategy: dict[str, Any] | None,
        route_decision: "RouteDecision | None" = None,
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
        intent: str,
        start_time: float,
        gateway: Any = None,
    ) -> ToolCallResult | None: ...

    def _resolve_scan_root_path(self, path_value: Any, execution_workspace: str | None) -> str: ...


class FunctionCallingToolExecutionMixin:
    """Execute concrete tool calls and skill-backed tools."""

    async def _execute_tool_call(
        self,
        tool_call: ToolCall,
        user_id: str,
        session_id: str | None,
        turn_id: str | None,
        intent: str,
        execution_agent_id: str,
        execution_workspace: str | None,
        orchestration_strategy: dict[str, Any] | None,
        session_run_id: str | None = None,
        session_run_revision: int = 0,
        user_message: str | None = None,
        iteration: int | None = None,
        cancel_token: CancelToken | None = None,
        recent_messages: list[dict[str, Any]] | None = None,
        route_decision: "RouteDecision | None" = None,
    ) -> ToolCallResult:
        """Execute a single tool call."""
        host = cast(_FunctionCallingToolExecutionHostProtocol, self)
        start_time = time.time()
        token = cancel_token if cancel_token is not None else null_cancel_token()

        tool_name = tool_call.name
        arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
        # Phase 3: auto-inject conversation_context for memory_query so the
        # indexical resolver can anchor deictic references (e.g. "当时", "just
        # now"). The chat LLM rarely populates this parameter on its own.
        arguments = _inject_memory_query_context(tool_name, arguments, recent_messages)
        workspace_root = host._resolve_execution_workspace(execution_workspace)

        if await token.is_cancelled():
            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                error="Run cancelled before tool execution",
                error_code="CANCELLED",
                execution_time=time.time() - start_time,
            )

        try:
            from ....tools.schema import ToolExecutionContext

            if tool_name.startswith("skill_"):
                skill_name = tool_name.replace("skill_", "")
                return await self._execute_skill(
                    skill_name=skill_name,
                    arguments=arguments,
                    user_id=user_id,
                    execution_workspace=execution_workspace,
                    session_id=session_id,
                    turn_id=turn_id,
                    tool_call_id=tool_call.id,
                    iteration=iteration,
                )

            if tool_name == "todo_write" and (
                str(intent or "").startswith("worker_")
                or str(execution_agent_id or "").startswith("worker_")
            ):
                return ToolCallResult(
                    tool_call_id=tool_call.id,
                    tool_name=tool_name,
                    success=False,
                    error=(
                        "todo_write is owned by the parent task agent; "
                        "worker agents must report progress through worker results."
                    ),
                    error_code="ROLE_NOT_ALLOWED",
                    execution_time=time.time() - start_time,
                )

            arguments, guardrail_error = host._apply_worker_explore_guardrails(
                intent=intent,
                tool_name=tool_name,
                arguments=arguments,
                execution_workspace=execution_workspace,
            )
            if guardrail_error:
                guardrail_error_code = host._classify_guardrail_error_code(
                    tool_name=tool_name,
                    error_text=guardrail_error,
                )
                logger.warning(
                    "[FunctionCalling] Blocked by guardrail: %s | intent=%s | workspace=%s | args=%s | reason=%s",
                    tool_name,
                    intent,
                    workspace_root,
                    arguments,
                    guardrail_error,
                )
                return ToolCallResult(
                    tool_call_id=tool_call.id,
                    tool_name=tool_name,
                    success=False,
                    error=guardrail_error,
                    error_code=guardrail_error_code,
                    execution_time=time.time() - start_time,
                )

            permissions = ["authenticated"]
            tool_info = host.tool_registry.get_tool_info(tool_name)
            if tool_info and tool_info.get("dangerous", False):
                permissions.append("dangerous_tools")
            normalized_session_id = str(session_id or "").strip()
            normalized_turn_id = str(turn_id or "").strip()
            target_task_agent_id = normalized_session_id or user_id
            trace_parent_span_id = (
                host._build_tool_span_id(normalized_turn_id, iteration, tool_call.id)
                if normalized_turn_id and iteration is not None and iteration > 0
                else ""
            )

            context = ToolExecutionContext(
                agent_id=execution_agent_id,
                workspace=workspace_root,
                env_vars={
                    "user_id": user_id,
                    "session_id": session_id or "",
                    "turn_id": turn_id or "",
                    "intent": intent,
                    "run_id": session_run_id or "",
                    "run_revision": str(session_run_revision),
                    "target_task_agent_type": "chat",
                    "target_task_agent_id": target_task_agent_id,
                    "trace_id": f"trace:{normalized_turn_id}" if normalized_turn_id else "",
                    "trace_parent_span_id": trace_parent_span_id,
                    "trace_tool_call_id": tool_call.id,
                    "current_user_text": user_message or "",
                },
                permissions=permissions,
                cancellation=token,
                capabilities=build_tool_capabilities(),
            )

            if tool_name == "agent":
                arguments = host._normalize_agent_launch_arguments(
                    arguments=arguments,
                    orchestration_strategy=orchestration_strategy,
                    route_decision=route_decision,
                )

            gateway = host._resolve_permission_gateway()
            if gateway is not None:
                denied_result = await host._gate_tool_call(
                    tool_call=tool_call,
                    tool_name=tool_name,
                    arguments=arguments,
                    agent_id=execution_agent_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    workspace=context.workspace,
                    intent=intent,
                    start_time=start_time,
                    gateway=gateway,
                )
                if denied_result is not None:
                    return denied_result

            if tool_name in host._FILE_SCAN_TOOLS:
                logger.info(
                    "[FunctionCalling] Executing scan tool: %s | workspace=%s | path=%s | args=%s",
                    tool_name,
                    workspace_root,
                    host._resolve_scan_root_path(arguments.get("path"), execution_workspace),
                    arguments,
                )
            else:
                logger.info(
                    "[FunctionCalling] Executing: %s with args: %s",
                    tool_name,
                    arguments,
                )
            from ...execution.tool_invocation_service import (
                InvocationContext,
                ToolCall as _ServiceToolCall,
                get_tool_invocation_service,
            )
            from ....events.domain_payloads import TaskContext

            if not hasattr(host, "_tool_invocation_service"):
                host._tool_invocation_service = get_tool_invocation_service(host.tool_registry)

            result = await host._tool_invocation_service.invoke(
                _ServiceToolCall(name=tool_name, args=arguments),
                InvocationContext(
                    tool_category="external_tool",
                    task_context=TaskContext(
                        session_id=session_id,
                        turn_id=turn_id,
                        task_id=getattr(context, "task_id", None),
                        user_id=user_id,
                    ),
                    execution_context=context,
                ),
            )
            execution_time = time.time() - start_time
            if not result.success:
                logger.warning(
                    "[FunctionCalling] Tool failed: %s | error=%s | code=%s",
                    tool_name,
                    result.error,
                    result.error_code,
                )
            if (
                tool_name in host._FILE_SCAN_TOOLS
                and execution_time >= host._SLOW_SCAN_WARNING_SECONDS
            ):
                logger.warning(
                    "[FunctionCalling] Slow scan tool: %s | workspace=%s | path=%s | elapsed_ms=%.1f | args=%s",
                    tool_name,
                    workspace_root,
                    host._resolve_scan_root_path(arguments.get("path"), execution_workspace),
                    execution_time * 1000,
                    arguments,
                )

            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=result.success,
                data=result.data,
                error=result.error,
                error_code=getattr(result, "error_code", None),
                execution_time=execution_time,
            )

        except Exception as exc:
            logger.error("[FunctionCalling] Tool execution error: %s", exc)
            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                error=str(exc),
                execution_time=time.time() - start_time,
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
        if not host.skill_runner:
            return ToolCallResult(
                tool_call_id="",
                tool_name=skill_name,
                success=False,
                error="Skill runner not available",
            )

        workspace_root = host._resolve_execution_workspace(execution_workspace)

        from ....hooks.contracts import HookEventType, HookOutcome
        from ....hooks.dispatch import dispatch_hook

        pre_decision = await dispatch_hook(
            HookEventType.PRE_SKILL_USE,
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_id,
            workspace=workspace_root,
            skill_name=skill_name,
            arguments=arguments,
        )
        if pre_decision.outcome == HookOutcome.DENY:
            return ToolCallResult(
                tool_call_id=tool_call_id or "",
                tool_name=skill_name,
                success=False,
                error=pre_decision.reason or "Skill call denied by hook",
                error_code="HOOK_DENIED",
            )
        if pre_decision.outcome == HookOutcome.MODIFY and pre_decision.modified_arguments is not None:
            arguments = dict(pre_decision.modified_arguments)

        skill_context = {
            "user_id": user_id,
            "session_id": f"session_{user_id}",
            "workspace": workspace_root,
            "env_vars": {
                "user": getpass.getuser(),
                "HOME": os.path.expanduser("~"),
                "PWD": workspace_root,
            },
        }

        from ....events.tracing import start_async_span, current_trace_context
        from ....runtime_trace import build_root_span_id, build_trace_id, normalize_turn_id

        normalized_turn_id = normalize_turn_id(turn_id)
        trace_id = (
            build_trace_id(normalized_turn_id)
            if normalized_turn_id and current_trace_context() is None
            else None
        )
        parent_span_id = None
        if trace_id and normalized_turn_id:
            parent_span_id = (
                host._build_tool_span_id(normalized_turn_id, iteration, tool_call_id or "")
                if iteration is not None and iteration > 0 and tool_call_id
                else build_root_span_id(normalized_turn_id)
            )

        args_list: list[str] = []
        if arguments:
            for value in arguments.values():
                if isinstance(value, str):
                    args_list.append(value)
                elif value is not None:
                    args_list.append(str(value))

        started_at = time.time()
        started_mono = time.monotonic()
        args_summary = str(arguments)[:500] if arguments else None

        async with start_async_span(
            node_type="skill_call",
            name=skill_name,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
        ) as span:
            span.set_turn_id(turn_id)
            span.set_attributes(
                {
                    "skill_name": skill_name,
                    "tool_call_id": tool_call_id,
                    "args_summary": args_summary,
                    "started_at": started_at,
                    "session_id": session_id,
                    "user_id": user_id,
                }
            )
            try:
                result = await host.skill_runner.execute(
                    skill_name=skill_name,
                    arguments=args_list,
                    context=skill_context,
                )
                duration_ms = (time.monotonic() - started_mono) * 1000
                finished_at = time.time()
                success = bool(getattr(result, "success", False))
                content = getattr(result, "content", None)
                result_summary = str(content)[:500] if content is not None else None
                metadata = getattr(result, "metadata", {}) or {}
                fork_mode = bool(metadata.get("fork_mode") or metadata.get("context") == "fork")
                allowed_tools = metadata.get("allowed_tools")
                if isinstance(allowed_tools, (list, tuple)):
                    allowed_tools_tuple = tuple(str(t) for t in allowed_tools)
                else:
                    allowed_tools_tuple = None

                span.set_attributes(
                    {
                        "success": success,
                        "execution_time_ms": int(duration_ms),
                        "finished_at": finished_at,
                        "result_summary": result_summary,
                        "fork_mode": fork_mode,
                        "allowed_tools": (
                            list(allowed_tools_tuple) if allowed_tools_tuple else None
                        ),
                    }
                )
                span.set_result_preview(result_summary)

                error = getattr(result, "error", None)
                if not success:
                    span.set_status("error")
                    from ....events.domain_payloads import ToolError as _ToolError
                    span._error = _ToolError(
                        type="SkillFailure",
                        message=str(error or "")[:1000],
                    )

                await self._publish_skill_invocation_event(
                    skill_name=skill_name,
                    success=success,
                    duration_ms=duration_ms,
                    started_at=started_at,
                    finished_at=finished_at,
                    fork_mode=fork_mode,
                    args_summary=args_summary,
                    result_summary=result_summary,
                    allowed_tools=allowed_tools_tuple,
                    error_message=str(error) if (not success and error) else None,
                    session_id=session_id,
                    turn_id=turn_id,
                    user_id=user_id,
                )

                await dispatch_hook(
                    HookEventType.POST_SKILL_USE,
                    session_id=session_id,
                    turn_id=turn_id,
                    user_id=user_id,
                    workspace=workspace_root,
                    skill_name=skill_name,
                    arguments=arguments,
                    extra={
                        "success": success,
                        "duration_ms": duration_ms,
                        "result_summary": result_summary,
                        "fork_mode": fork_mode,
                        "error_message": str(error) if (not success and error) else None,
                    },
                )

                return ToolCallResult(
                    tool_call_id=tool_call_id or "",
                    tool_name=skill_name,
                    success=success,
                    data=content,
                    error=error,
                )

            except Exception as exc:
                duration_ms = (time.monotonic() - started_mono) * 1000
                finished_at = time.time()
                logger.error("[FunctionCalling] Skill execution error: %s", exc)
                span.set_attributes(
                    {
                        "success": False,
                        "execution_time_ms": int(duration_ms),
                        "finished_at": finished_at,
                        "error_message": str(exc)[:1000],
                    }
                )
                await self._publish_skill_invocation_event(
                    skill_name=skill_name,
                    success=False,
                    duration_ms=duration_ms,
                    started_at=started_at,
                    finished_at=finished_at,
                    fork_mode=False,
                    args_summary=args_summary,
                    result_summary=None,
                    allowed_tools=None,
                    error_message=str(exc),
                    session_id=session_id,
                    turn_id=turn_id,
                    user_id=user_id,
                )
                return ToolCallResult(
                    tool_call_id=tool_call_id or "",
                    tool_name=skill_name,
                    success=False,
                    error=str(exc),
                )

    async def _publish_skill_invocation_event(
        self,
        *,
        skill_name: str,
        success: bool,
        duration_ms: float,
        started_at: float,
        finished_at: float,
        fork_mode: bool,
        args_summary: str | None,
        result_summary: str | None,
        allowed_tools: tuple[str, ...] | None,
        error_message: str | None,
        session_id: str | None,
        turn_id: str | None,
        user_id: str | None,
    ) -> None:
        """Publish SkillInvocationCompleted to the message bus (best-effort)."""
        try:
            from ....events.events import Event, EventTypes
            from ....events.domain_payloads import (
                SkillInvocationCompleted,
                TaskContext,
                ToolError,
            )
            from ....core.container import get_container

            bus = get_container().message_bus()
            if bus is None or not hasattr(bus, "publish"):
                return
            payload = SkillInvocationCompleted(
                skill_name=skill_name,
                success=success,
                duration_ms=duration_ms,
                started_at=started_at,
                finished_at=finished_at,
                fork_mode=fork_mode,
                args_summary=args_summary,
                result_summary=result_summary,
                allowed_tools=allowed_tools,
                error=(
                    ToolError(type="SkillFailure", message=error_message[:1000])
                    if error_message
                    else None
                ),
                context=TaskContext(
                    session_id=session_id,
                    turn_id=turn_id,
                    task_id=None,
                    user_id=user_id,
                ),
            )
            await bus.publish(Event(
                type=EventTypes.SKILL_INVOCATION_COMPLETED,
                data=payload,
                source="skill_runner",
            ))
        except Exception:
            logger.exception("publish SkillInvocationCompleted failed (skill=%s)", skill_name)


__all__ = ["FunctionCallingToolExecutionMixin"]
