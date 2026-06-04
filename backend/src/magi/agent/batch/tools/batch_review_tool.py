"""Agent tool: apply a human review decision to a needs_review item."""
from __future__ import annotations

from typing import Any, Dict

from ..store import default_batch_store

# agent.batch.tools is host runtime-control code (L12). Import the Tool base +
# schema helpers straight from the SDK (downward, legal), mirroring how
# magi.agent.runtime_tools.agent_tool imports its contracts.
from magi_plugin_sdk import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

_DECISIONS = ["approve", "override", "skip"]


class BatchReviewTool(Tool):
    """Resolve a needs_review item: approve/override -> pending; skip -> skipped."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="batch_review",
            description=(
                "Apply a review decision to a needs_review batch item. "
                "approve/override -> item returns to pending (re-processed, decision "
                "recorded); skip -> skipped. Use after surfacing the review list."
            ),
            category="automation",
            parameters=[
                ToolParameter(
                    name="job_id", type=ParameterType.STRING, required=True,
                    description="The batch job id.",
                ),
                ToolParameter(
                    name="item_id", type=ParameterType.STRING, required=True,
                    description="The item to resolve.",
                ),
                ToolParameter(
                    name="decision", type=ParameterType.STRING, required=True,
                    enum=_DECISIONS, description="approve | override | skip.",
                ),
                ToolParameter(
                    name="data", type=ParameterType.OBJECT, required=False,
                    description="Optional override payload (e.g. a corrected name).",
                ),
            ],
        )

    async def execute(
        self, parameters: Dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        decision = parameters.get("decision")
        if decision not in _DECISIONS:
            return ToolResult(
                success=False, error=f"decision must be one of {_DECISIONS}",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )
        store = default_batch_store()
        applied = await store.apply_review(
            parameters["job_id"],
            parameters["item_id"],
            decision,
            data=parameters.get("data"),
        )
        return ToolResult(success=True, data={"applied": applied})
