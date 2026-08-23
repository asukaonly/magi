"""Builtin tool for querying recent execution trace details."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from ..schema import ParameterType, Tool, ToolExecutionContext, ToolParameter, ToolResult, ToolSchema


@dataclass(frozen=True)
class _TraceQueryRequest:
    user_id: str
    session_id: str
    requested_turn_id: str | None
    current_turn_id: str | None
    scope: str
    query: str
    tool_name_filter: str
    include_arguments: bool
    include_result_json: bool


class TraceQueryTool(Tool):
    """Query recent chat trace details for audit-style follow-up questions."""

    SCOPE_PREVIOUS = "previous_turn"
    SCOPE_CURRENT = "current_turn"
    SCOPE_LATEST = "latest_session_turn"

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="trace_query",
            description=(
                "Inspect recent chat execution traces for exact tool details such as which tool ran, "
                "its arguments, duration, and failure information. Prefer this when the user asks "
                "about the tool execution process itself rather than the domain answer."
            ),
            category="debug",
            parameters=self._trace_query_parameters(),
            tags=["trace", "debug", "audit", "tools"],
            effect_replay_policy="read_only",
            timeout=15,
        )

    def _trace_query_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type=ParameterType.STRING,
                description="The user question about recent tool execution details.",
                required=True,
            ),
            ToolParameter(
                name="scope",
                type=ParameterType.STRING,
                description="Which turn to inspect when turn_id is not explicitly provided.",
                required=False,
                default=self.SCOPE_PREVIOUS,
                enum=[self.SCOPE_PREVIOUS, self.SCOPE_CURRENT, self.SCOPE_LATEST],
            ),
            ToolParameter(
                name="turn_id",
                type=ParameterType.STRING,
                description="Optional explicit turn id to inspect.",
                required=False,
            ),
            ToolParameter(
                name="tool_name",
                type=ParameterType.STRING,
                description="Optional tool name filter.",
                required=False,
            ),
            ToolParameter(
                name="include_arguments",
                type=ParameterType.BOOLEAN,
                description="Whether to include parsed tool arguments in the response.",
                required=False,
                default=True,
            ),
            ToolParameter(
                name="include_result_json",
                type=ParameterType.BOOLEAN,
                description="Whether to include full parsed result_json in the debug payload.",
                required=False,
                default=False,
            ),
        ]

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        request = self._prepare_query_request(parameters, context)
        if isinstance(request, ToolResult):
            return request

        trace_service = self._trace_capability(context)
        if isinstance(trace_service, ToolResult):
            return trace_service

        resolved_turn_id = self._resolve_query_turn_id(
            trace_service=trace_service,
            request=request,
        )
        if isinstance(resolved_turn_id, ToolResult):
            return resolved_turn_id

        snapshot = self._trace_snapshot(trace_service, request, resolved_turn_id)
        if isinstance(snapshot, ToolResult):
            return snapshot

        tool_calls = self._collect_tool_calls(
            snapshot.get("root"),
            tool_name_filter=request.tool_name_filter,
            include_arguments=request.include_arguments,
            include_result_json=request.include_result_json,
        )
        missing_tool = self._missing_tool_call_result(request, resolved_turn_id, tool_calls)
        if missing_tool is not None:
            return missing_tool

        summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
        return self._success_result(
            request=request,
            resolved_turn_id=resolved_turn_id,
            snapshot=snapshot,
            summary=summary,
            tool_calls=tool_calls,
        )

    def _prepare_query_request(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> _TraceQueryRequest | ToolResult:
        user_id = str(parameters.get("user_id") or context.env_vars.get("user_id") or "").strip()
        session_id = str(parameters.get("session_id") or context.env_vars.get("session_id") or "").strip()
        if not user_id or not session_id:
            return ToolResult(
                success=False,
                error="trace_query requires user_id and session_id",
                error_code="MISSING_CONTEXT",
            )
        return _TraceQueryRequest(
            user_id=user_id,
            session_id=session_id,
            requested_turn_id=str(parameters.get("turn_id") or "").strip() or None,
            current_turn_id=str(context.env_vars.get("turn_id") or "").strip() or None,
            scope=str(parameters.get("scope") or self.SCOPE_PREVIOUS).strip() or self.SCOPE_PREVIOUS,
            query=str(parameters.get("query") or "").strip(),
            tool_name_filter=str(parameters.get("tool_name") or "").strip(),
            include_arguments=bool(parameters.get("include_arguments", True)),
            include_result_json=bool(parameters.get("include_result_json", False)),
        )

    @staticmethod
    def _trace_capability(context: ToolExecutionContext) -> Any | ToolResult:
        if context.capabilities is None or context.capabilities.trace is None:
            return ToolResult(
                success=False,
                error="trace capability unavailable",
                error_code="CAPABILITY_UNAVAILABLE",
            )
        return context.capabilities.trace

    def _resolve_query_turn_id(
        self,
        *,
        trace_service: Any,
        request: _TraceQueryRequest,
    ) -> str | ToolResult:
        resolved_turn_id = request.requested_turn_id or self._resolve_turn_id(
            trace_service=trace_service,
            user_id=request.user_id,
            session_id=request.session_id,
            scope=request.scope,
            current_turn_id=request.current_turn_id,
        )
        if resolved_turn_id:
            return resolved_turn_id
        return ToolResult(
            success=False,
            error="No matching traced turn found for this session",
            error_code="TRACE_NOT_FOUND",
        )

    @staticmethod
    def _trace_snapshot(
        trace_service: Any,
        request: _TraceQueryRequest,
        resolved_turn_id: str,
    ) -> dict[str, Any] | ToolResult:
        snapshot = trace_service.get_trace_snapshot(
            user_id=request.user_id,
            session_id=request.session_id,
            turn_id=resolved_turn_id,
        )
        if isinstance(snapshot, dict):
            return snapshot
        return ToolResult(
            success=False,
            error=f"No trace snapshot found for turn {resolved_turn_id}",
            error_code="TRACE_NOT_FOUND",
        )

    @staticmethod
    def _missing_tool_call_result(
        request: _TraceQueryRequest,
        resolved_turn_id: str,
        tool_calls: list[dict[str, Any]],
    ) -> ToolResult | None:
        if not request.tool_name_filter or tool_calls:
            return None
        return ToolResult(
            success=False,
            error=f"No tool call named {request.tool_name_filter} found in turn {resolved_turn_id}",
            error_code="TOOL_CALL_NOT_FOUND",
        )

    def _success_result(
        self,
        *,
        request: _TraceQueryRequest,
        resolved_turn_id: str,
        snapshot: dict[str, Any],
        summary: dict[str, Any],
        tool_calls: list[dict[str, Any]],
    ) -> ToolResult:
        return ToolResult(
            success=True,
            data={
                "summary_markdown": self._build_summary_markdown(
                    query=request.query,
                    turn_id=resolved_turn_id,
                    summary=summary,
                    tool_calls=tool_calls,
                ),
                "trace": {
                    "turn_id": resolved_turn_id,
                    "scope": request.scope,
                    "headline": summary.get("headline") or "",
                    "status": summary.get("status") or snapshot.get("status") or "unknown",
                    "duration_seconds": summary.get("duration_seconds"),
                },
                "tool_calls": tool_calls,
            },
        )

    def is_ready(self) -> bool:
        return True

    def _resolve_turn_id(
        self,
        *,
        trace_service: Any,
        user_id: str,
        session_id: str,
        scope: str,
        current_turn_id: str | None,
    ) -> str | None:
        if scope == self.SCOPE_CURRENT and current_turn_id:
            return current_turn_id
        activity_map = trace_service.get_turn_activity_map(user_id=user_id, session_id=session_id)
        if not isinstance(activity_map, dict) or not activity_map:
            return None
        turn_ids = [str(turn_id).strip() for turn_id in activity_map.keys() if str(turn_id).strip()]
        if scope == self.SCOPE_LATEST:
            return turn_ids[-1] if turn_ids else None
        for turn_id in reversed(turn_ids):
            if current_turn_id and turn_id == current_turn_id:
                continue
            return turn_id
        return turn_ids[-1] if turn_ids else None

    def _collect_tool_calls(
        self,
        root: Any,
        *,
        tool_name_filter: str,
        include_arguments: bool,
        include_result_json: bool,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for node in self._walk_nodes(root):
            if not isinstance(node, dict) or str(node.get("kind") or "") != "tool":
                continue
            metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
            tool_name = str(metadata.get("tool_name") or node.get("label") or "unknown").strip()
            if tool_name_filter and tool_name != tool_name_filter:
                continue
            item: dict[str, Any] = {
                "tool_name": tool_name,
                "status": str(node.get("status") or "unknown"),
                "duration_ms": metadata.get("execution_time") if metadata.get("execution_time") is not None else metadata.get("duration_ms"),
                "result_preview": str(node.get("result_preview") or "").strip(),
                "error": str(node.get("error") or "").strip() or None,
            }
            if include_arguments:
                arguments = metadata.get("arguments")
                if isinstance(arguments, dict) and arguments:
                    item["arguments"] = arguments
            if include_result_json:
                result_json = metadata.get("result_json")
                if result_json is not None:
                    item["result_json"] = result_json
            if item["error"]:
                item["error_code"] = self._extract_error_code(item["error"])
            results.append(item)
        return results

    def _walk_nodes(self, node: Any) -> list[dict[str, Any]]:
        if not isinstance(node, dict):
            return []
        nodes = [node]
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                nodes.extend(self._walk_nodes(child))
        return nodes

    @staticmethod
    def _extract_error_code(error_text: str) -> str | None:
        text = str(error_text or "").strip()
        if not text:
            return None
        head = text.split(":", 1)[0].strip()
        if head and head.isupper() and len(head) <= 40:
            return head
        return None

    def _build_summary_markdown(
        self,
        *,
        query: str,
        turn_id: str,
        summary: dict[str, Any],
        tool_calls: list[dict[str, Any]],
    ) -> str:
        lines = [
            "# Trace Query Result",
            f"- Query: {query or 'recent tool execution details'}",
            f"- Turn ID: {turn_id}",
            f"- Status: {summary.get('status') or 'unknown'}",
        ]
        duration_seconds = summary.get("duration_seconds")
        if duration_seconds not in (None, ""):
            lines.append(f"- Turn Duration: {duration_seconds}s")
        headline = str(summary.get("headline") or "").strip()
        if headline:
            lines.append(f"- Headline: {headline}")
        if not tool_calls:
            lines.append("")
            lines.append("No tool calls were recorded for the resolved turn.")
            return "\n".join(lines)
        lines.append("")
        lines.append("## Tool Calls")
        for item in tool_calls:
            line = f"- {item['tool_name']}: {item['status']}"
            if item.get("duration_ms") not in (None, ""):
                line += f" | duration_ms={item['duration_ms']}"
            result_preview = str(item.get("result_preview") or "").strip()
            if result_preview:
                line += f" | result={result_preview}"
            if item.get("error"):
                line += f" | error={item['error']}"
            lines.append(line)
            arguments = item.get("arguments")
            if isinstance(arguments, dict) and arguments:
                lines.append(f"  args: {arguments}")
        return "\n".join(lines)
