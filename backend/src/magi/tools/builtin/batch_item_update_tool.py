"""Agent tool: write item outcomes back to the batch manifest (array)."""
from __future__ import annotations

from typing import Any, Dict

from ...agent.batch import BatchItemStatus, ItemOutcome
from ...agent.batch.store import default_batch_store
from ..schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)


class BatchItemUpdateTool(Tool):
    """Apply a batch of item outcomes. Only items currently 'running' change."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="batch_item_update",
            description=(
                "Write outcomes for one or more batch items back to the manifest. "
                "Call incrementally as you finish items. Each update needs item_id + "
                "status (done|failed|needs_review|skipped); optional result, "
                "review_reason, error. Items not currently 'running' are left untouched."
            ),
            category="automation",
            parameters=[
                ToolParameter(
                    name="job_id", type=ParameterType.STRING, required=True,
                    description="The batch job id.",
                ),
                ToolParameter(
                    name="updates", type=ParameterType.ARRAY, required=True,
                    array_item_type=ParameterType.OBJECT,
                    description="List of {item_id, status, result?, review_reason?, error?}.",
                ),
            ],
        )

    async def execute(
        self, parameters: Dict[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        job_id = parameters.get("job_id")
        raw = parameters.get("updates") or []
        if not job_id or not isinstance(raw, list):
            return ToolResult(
                success=False, error="job_id and updates[] are required",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )
        try:
            outcomes = [
                ItemOutcome(
                    item_id=u["item_id"],
                    status=BatchItemStatus(u["status"]),
                    result=u.get("result"),
                    review_reason=u.get("review_reason"),
                    error=u.get("error"),
                )
                for u in raw
            ]
        except (KeyError, ValueError) as exc:
            return ToolResult(
                success=False, error=f"bad update entry: {exc}",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        store = default_batch_store()
        applied = await store.update_items(job_id, outcomes)
        return ToolResult(success=True, data={"applied": applied})
