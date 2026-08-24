"""Runtime control for requesting deeper reasoning on a later model step."""

from __future__ import annotations

from typing import Any, Dict

from magi_plugin_sdk.tools import (
    ParameterType,
    Tool,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)


class RequestReasoningDepthTool(Tool):
    """Let the model request one bounded reasoning-depth escalation."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="request_reasoning_depth",
            description=(
                "Request one reasoning-depth increase for the next model step when "
                "additional reasoning may change the decision. The runtime may deny "
                "the request because of the user's mode, depth limit, or escalation "
                "budget. Do not use this for permission, network, dependency, user-input, "
                "uncertain-effect, or exhausted-budget blockers."
            ),
            category="control",
            effect_class="read_only",
            effect_replay_policy="idempotent",
            parameters=[
                ToolParameter(
                    name="reason",
                    type=ParameterType.STRING,
                    description="Stable reason for requesting more reasoning.",
                    required=True,
                    enum=[
                        "task_complexity",
                        "conflicting_evidence",
                        "stalled_reasoning",
                        "user_requested_deeper_analysis",
                    ],
                )
            ],
            tags=["control", "reasoning"],
            timeout=5,
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        _ = context
        reason = str(parameters.get("reason") or "").strip()
        if reason not in {
            "task_complexity",
            "conflicting_evidence",
            "stalled_reasoning",
            "user_requested_deeper_analysis",
        }:
            return ToolResult(
                success=False,
                error="request_reasoning_depth requires a supported reason",
                error_code="INVALID_REASONING_ESCALATION_REASON",
            )
        return ToolResult(
            success=True,
            data={
                "status": "requested",
                "reason": reason,
            },
        )


__all__ = ["RequestReasoningDepthTool"]
