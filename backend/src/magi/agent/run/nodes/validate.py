"""ValidateNode: invoke VerifyTool against session-changed files.

Phase D scope: profile=coding turns auto-append ValidateNode after the
primary node (ToolLoop or PlanFanout). The Node invokes the existing
``verify`` tool with ``mode=changed`` to run file-type-aware sanity
checks on every file edited in the current session workspace.

Outcome mapping:
- verify reports success AND no failures → NodeResult(DONE) with summary
- verify reports file-level failures (data["summary"]["fail"] > 0) → NodeResult(FAILED)
- verify tool itself fails (success=False) → NodeResult(FAILED)
- tool itself raises → NodeResult(FAILED) with exception message

ValidateNode does NOT gate on profile — that's GraphBuilder's job.
The Node assumes if it's invoked, validation is wanted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ....events.domain_payloads import TaskContext
from ..nodes.protocol import NodeOutcome, NodeResult
from ....tools.schema import ToolExecutionContext
from magi.tools.capabilities import build_tool_capabilities

if TYPE_CHECKING:
    from ...task_agents.common.contracts import ExecutionRequest


class ValidateNode:
    """Run ``verify`` tool with ``mode=changed`` against the session workspace."""

    node_type: str = "validate"

    __slots__ = ("_tool_invocation_service",)

    def __init__(self, tool_invocation_service: Any) -> None:
        """Initialize the node with the canonical tool invocation service."""
        self._tool_invocation_service = tool_invocation_service

    async def execute(self, request: "ExecutionRequest") -> NodeResult:
        try:
            from ...execution.tool_invocation_service import ToolCall  # noqa: PLC0415

            invocation_context = self._build_invocation_context(request)
            tool_result = await self._tool_invocation_service.invoke(
                ToolCall(name="verify", args={"mode": "changed"}),
                invocation_context,
            )
        except Exception as exc:
            return NodeResult(outcome=NodeOutcome.FAILED, error=str(exc))

        if tool_result is None:
            return NodeResult(
                outcome=NodeOutcome.FAILED,
                error="verify tool returned None",
            )

        # The verify tool itself failed (bad args, internal crash, permission denied, etc.)
        if not tool_result.success:
            return NodeResult(
                outcome=NodeOutcome.FAILED,
                error=getattr(tool_result, "error", None) or "verify tool reported failure",
            )

        # Tool ran successfully — now check whether any individual file
        # verification failed by inspecting data["summary"].
        raw_data = getattr(tool_result, "data", None)
        data = raw_data if isinstance(raw_data, dict) else {}
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        if not isinstance(summary, dict):
            summary = {}
        fail_count = int(summary.get("fail", 0) or 0)
        timeout_count = int(summary.get("timeout", 0) or 0)

        if fail_count > 0 or timeout_count > 0:
            # File-level failures: collect the failed paths from results[]
            results = data.get("results") if isinstance(data.get("results"), list) else []
            failed_paths = [
                str(r.get("path", "(unknown)")) for r in (results or [])
                if isinstance(r, dict) and r.get("status") in {"fail", "timeout"}
            ]
            return NodeResult(
                outcome=NodeOutcome.FAILED,
                error=(
                    f"Verification failed: {fail_count} failed, {timeout_count} timed out. "
                    f"Files: {', '.join(failed_paths) or '(unknown)'}"
                ),
            )

        # All verifications passed (or no files changed)
        # Lazy import to avoid circular dependency via task_agents.__init__
        from ...task_agents.common.contracts import ExecutionMode, ExecutionResult  # noqa: PLC0415

        pass_count = int(summary.get("pass", 0) or 0)
        skipped_count = int(summary.get("skipped", 0) or 0)
        if pass_count == 0 and skipped_count == 0:
            summary_text = "No files changed since last verification"
        else:
            summary_text = (
                f"Verified {pass_count} file(s)"
                + (f", {skipped_count} skipped" if skipped_count else "")
                + " — all passed"
            )

        return NodeResult(
            outcome=NodeOutcome.DONE,
            execution_result=ExecutionResult(
                mode=ExecutionMode.DIRECT_LLM,  # Validate has no real mode; reuse DIRECT_LLM as inert
                response_text=f"[verify] {summary_text}",
            ),
        )

    def snapshot(self) -> dict[str, Any]:
        """ValidateNode is stateless — no in-flight state to capture."""
        return {}

    def restore(self, state: dict[str, Any]) -> None:
        """No-op: stateless."""
        return None

    @staticmethod
    def _build_tool_context(request: "ExecutionRequest") -> ToolExecutionContext:
        """Build the ToolExecutionContext that VerifyTool requires.

        VerifyTool reads ``context.env_vars["session_id"]`` and
        ``context.workspace`` directly. Provide both.
        """
        ctx = getattr(request, "context", None)
        session_id = getattr(ctx, "session_id", None) or ""
        user_id = getattr(ctx, "user_id", None) or "validate_node"
        workspace_path = (
            getattr(getattr(ctx, "latest_payload", None), "workspace_path", None)
            or "./workspace"
        )
        return ToolExecutionContext(
            agent_id=user_id,
            workspace=workspace_path,
            env_vars={"session_id": str(session_id)},
            permissions=["authenticated", "dangerous_tools"],
            capabilities=build_tool_capabilities(),
        )

    @classmethod
    def _build_invocation_context(
        cls,
        request: "ExecutionRequest",
    ) -> Any:
        from ...execution.tool_invocation_service import InvocationContext  # noqa: PLC0415

        context = getattr(request, "context", None)
        latest_payload = getattr(context, "latest_payload", None)
        return InvocationContext(
            tool_category="validation",
            task_context=TaskContext(
                session_id=getattr(context, "session_id", None),
                turn_id=getattr(latest_payload, "turn_id", None),
                task_id=getattr(context, "session_run_id", None),
                user_id=getattr(context, "user_id", None),
            ),
            execution_context=cls._build_tool_context(request),
        )


__all__ = ["ValidateNode"]
