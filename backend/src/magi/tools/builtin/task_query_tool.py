"""Read user-owned background task state through the host capability boundary."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..schema import ParameterType, Tool, ToolExecutionContext, ToolParameter, ToolResult, ToolSchema


class _TaskQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task_id: str | None = Field(default=None, min_length=1, max_length=128)
    scope: Literal["session", "user"] = "session"
    status: Literal[
        "pending", "running", "cancelling", "cancelled", "succeeded", "failed",
        "suspended_waiting_user",
    ] | None = None
    limit: int = Field(default=10, ge=1, le=20)
    offset: int = Field(default=0, ge=0)


class TaskQueryTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="task_query",
            description=(
                "Read the actual status, result summary, failure, or waiting state of background tasks. "
                "Defaults to this conversation; use scope='user' for your user's tasks across conversations. "
                "Omit task_id to list recent tasks, then query an exact ID if needed. "
                "This never starts, retries, or cancels work. Use schedule for future reminders and "
                "scheduled jobs, agent for child runs, and trace_query for tool execution details. "
                "A running status does not imply a completion percentage or estimated finish time."
            ),
            category="system", effect_replay_policy="read_only", timeout=10,
            parameters=[
                ToolParameter(name="task_id", type=ParameterType.STRING, required=False,
                              description="Exact background task ID; omit to list recent tasks."),
                ToolParameter(name="scope", type=ParameterType.STRING, required=False,
                              enum=["session", "user"], default="session",
                              description="Current conversation or all conversations of the current user."),
                ToolParameter(name="status", type=ParameterType.STRING, required=False,
                              enum=["pending", "running", "cancelling", "cancelled", "succeeded",
                                    "failed", "suspended_waiting_user"],
                              description="Optional status filter for listing."),
                ToolParameter(name="limit", type=ParameterType.INTEGER, required=False, default=10,
                              description="Page size from 1 to 20."),
                ToolParameter(name="offset", type=ParameterType.INTEGER, required=False, default=0,
                              description="Nonnegative offset; use next_offset from the previous page."),
            ],
            tags=["tasks", "background", "status", "results"],
        )

    async def execute(self, parameters: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        try:
            request = _TaskQuery.model_validate(parameters)
        except ValidationError:
            return ToolResult(success=False, error="Invalid task query parameters", error_code="INVALID_PARAMETERS")
        user_id = context.env_vars.get("user_id", "").strip()
        session_id = context.env_vars.get("session_id", "").strip()
        if not user_id or (request.scope == "session" and not session_id):
            return ToolResult(success=False, error="Task query requires an active user and requested conversation scope",
                              error_code="TASK_SCOPE_UNAVAILABLE")
        port = context.capabilities.task_query if context.capabilities else None
        if port is None:
            return ToolResult(success=False, error="Background task queries are unavailable", error_code="TASK_QUERY_UNAVAILABLE")
        try:
            data = await port.query(
                user_id=user_id, session_id=session_id if request.scope == "session" else None,
                task_id=request.task_id, status=request.status, limit=request.limit, offset=request.offset,
            )
        except LookupError:
            return ToolResult(success=False, error="Task not found in the requested scope", error_code="TASK_NOT_FOUND")
        return ToolResult(success=True, data={**data, "scope": request.scope})
