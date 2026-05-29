"""ValidateNode: invoke VerifyTool against session-changed files.

Phase D scope: profile=coding turns auto-append ValidateNode after the
primary node (ToolLoop or PlanFanout). The Node invokes the existing
``verify`` tool with ``mode=changed`` to run file-type-aware sanity
checks on every file edited in the current session workspace.

Outcome mapping:
- verify reports success → NodeResult(DONE) with summary in ExecutionResult.response_text
- verify reports errors → NodeResult(FAILED) with error message
- tool itself raises → NodeResult(FAILED) with exception message

ValidateNode does NOT gate on profile — that's GraphBuilder's job.
The Node assumes if it's invoked, validation is wanted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..nodes.protocol import NodeOutcome, NodeResult

if TYPE_CHECKING:
    from ...task_agents.common.contracts import ExecutionRequest


class ValidateNode:
    """Run ``verify`` tool with ``mode=changed`` against the session workspace."""

    node_type: str = "validate"

    __slots__ = ("_tool_registry",)

    def __init__(self, tool_registry: Any) -> None:
        """``tool_registry`` is the chat task agent's ToolRegistry — it
        exposes ``async execute_tool(*, tool_name, params, context)``."""
        self._tool_registry = tool_registry

    async def execute(self, request: "ExecutionRequest") -> NodeResult:
        try:
            tool_result = await self._tool_registry.execute_tool(
                tool_name="verify",
                params={"mode": "changed"},
                context=self._build_tool_context(request),
            )
        except Exception as exc:
            return NodeResult(outcome=NodeOutcome.FAILED, error=str(exc))

        if tool_result is None:
            return NodeResult(
                outcome=NodeOutcome.FAILED,
                error="verify tool returned None",
            )

        if not getattr(tool_result, "success", False):
            error_message = (
                getattr(tool_result, "error", None)
                or "Verification failed"
            )
            return NodeResult(outcome=NodeOutcome.FAILED, error=error_message)

        # Success: build a minimal ExecutionResult carrying the verify
        # summary. The chat coordinator's response merger appends this
        # text to the primary node's response.
        # Lazy import to avoid circular dependency via task_agents.__init__
        from ...task_agents.common.contracts import ExecutionMode, ExecutionResult  # noqa: PLC0415

        data = getattr(tool_result, "data", None) or {}
        summary = str(data.get("summary") if isinstance(data, dict) else None or "Verification passed")
        return NodeResult(
            outcome=NodeOutcome.DONE,
            execution_result=ExecutionResult(
                mode=ExecutionMode.DIRECT_LLM,  # Validate has no real mode; reuse DIRECT_LLM as inert
                response_text=f"[verify] {summary}",
            ),
        )

    @staticmethod
    def _build_tool_context(request: "ExecutionRequest") -> dict[str, Any]:
        """Extract the minimal context a tool needs: session + workspace."""
        ctx = getattr(request, "context", None)
        return {
            "session_id": getattr(ctx, "session_id", None),
            "user_id": getattr(ctx, "user_id", None),
            "workspace_path": getattr(
                getattr(ctx, "latest_payload", None), "workspace_path", None
            ),
        }


__all__ = ["ValidateNode"]
