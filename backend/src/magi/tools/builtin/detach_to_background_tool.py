"""Detach-to-background tool.

Lets the active LLM turn request that its run continue as a background
task. The tool is only usable while the orchestrator is actively hosting
the run (detect via :func:`current_detach_signal`); outside of that
context it reports a clear failure so a stray call cannot mutate
unrelated runtime state.

The actual handoff is a two-step dance:

1. This tool calls ``signal.request(...)`` which flips the
   :class:`DetachSignal` already observed by the orchestrator loop.
2. At the next tool boundary the orchestrator exits with
   ``ExecutionOutcome(status="detached")`` plus a
   :class:`OrchestratorSnapshot`, and a higher-level handler (chat
   post-processor) is responsible for seeding a
   :class:`BackgroundTaskSpec` from that snapshot.

Step 2 is not this tool's concern. All the tool does is record the
intent.
"""

from __future__ import annotations

from typing import Any, Dict

from magi.agent.run_control import DetachRequested, current_detach_signal

from ..schema import (
    ParameterType,
    Tool,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)


class DetachToBackgroundTool(Tool):
    """Request that the current run finish in the background."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="detach_to_background",
            description=(
                "Transfer the current task to a background worker so the "
                "user's chat turn can finish immediately. Use this when "
                "the task will clearly take a long time (deep research, "
                "broad scans, multi-step rollouts) and the user would "
                "prefer an async notification over waiting in-line. The "
                "run continues from its current point — all prior "
                "messages and tool results are preserved."
            ),
            category="system",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="reason",
                    type=ParameterType.STRING,
                    description=(
                        "Short machine label for why detaching now, e.g. "
                        "'long_running', 'deep_research', 'user_request'."
                    ),
                    required=False,
                    default="long_running",
                ),
                ToolParameter(
                    name="note",
                    type=ParameterType.STRING,
                    description=(
                        "Optional freeform note shown alongside the "
                        "background task (e.g. the summary of what is "
                        "being handed off)."
                    ),
                    required=False,
                    default="",
                ),
            ],
            examples=[
                {
                    "input": {
                        "reason": "deep_research",
                        "note": "scanning 400 commits",
                    },
                    "output": "detach_requested",
                }
            ],
            timeout=5,
            retry_on_failure=False,
            dangerous=False,
            tags=["system", "background", "runtime-control"],
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        _ = context  # unused; detach scope is bound via ContextVar
        signal = current_detach_signal()
        if signal is None:
            return ToolResult(
                success=False,
                error=(
                    "detach_to_background is only available while running "
                    "inside a function-calling orchestrator that exposes a "
                    "DetachSignal. It cannot be used from standalone tool "
                    "invocations."
                ),
                error_code="detach_not_supported",
            )

        reason = str(parameters.get("reason") or "long_running").strip() or "long_running"
        note = str(parameters.get("note") or "").strip()

        already_requested = signal.is_requested()
        if not already_requested:
            signal.request(
                DetachRequested(reason=reason, requested_by="llm", note=note)
            )

        return ToolResult(
            success=True,
            data={
                "status": "detach_requested",
                "reason": reason,
                "note": note,
                "already_requested": already_requested,
            },
        )
