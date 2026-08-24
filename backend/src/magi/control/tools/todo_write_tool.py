"""``todo_write`` — versioned mutations for the current run plan."""

from __future__ import annotations

from typing import Any, Dict

from magi.control.common.events import publish_control_todo_state_changed
from magi.control.provider import resolve_control_session_store
from magi.core.logger import get_logger
from magi.identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from magi.control.session_store import ControlSessionClearedError
from magi.control.run_plan import RunPlanError
from magi_plugin_sdk.tools import (
    ParameterType,
    Tool,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

logger = get_logger(__name__)


class TodoWriteTool(Tool):
    """Create or patch a runtime-owned plan using optimistic concurrency."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="todo_write",
            description=(
                "Create or update the current run plan. The runtime owns IDs, "
                "versions, and state transitions. Create with expected_version=0 "
                "and no plan_id. For every later mutation, send the returned "
                "plan_id and version. Items are patches, not a full replacement. "
                "A completed item must cite evidence_refs returned by earlier "
                "tool observations. At most one item may be in_progress."
            ),
            category="control",
            effect_class="external_write",
            parameters=[
                ToolParameter(
                    name="plan_id",
                    type=ParameterType.STRING,
                    description="Plan ID returned by the first mutation.",
                    required=False,
                ),
                ToolParameter(
                    name="expected_version",
                    type=ParameterType.INTEGER,
                    description="0 when creating; otherwise the last returned version.",
                    required=True,
                ),
                ToolParameter(
                    name="required",
                    type=ParameterType.BOOLEAN,
                    description="Whether Completion Gate must enforce this plan.",
                    required=False,
                ),
                ToolParameter(
                    name="status",
                    type=ParameterType.STRING,
                    description="Optional plan state: active, blocked, or cancelled.",
                    required=False,
                    enum=["active", "blocked", "cancelled"],
                ),
                ToolParameter(
                    name="items",
                    type=ParameterType.ARRAY,
                    array_item_type=ParameterType.OBJECT,
                    description=(
                        "Todo patches. New items omit id and require content. Existing "
                        "items use the returned id. Optional fields: content, required, "
                        "status (pending, in_progress, completed, blocked, skipped, "
                        "cancelled), evidence_refs, blocked_reason."
                    ),
                    required=True,
                ),
            ],
            tags=["control", "todo"],
            timeout=5,
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        raw_sid = context.env_vars.get("session_id")
        sid = str(raw_sid or "").strip()
        if not sid:
            return ToolResult(
                success=False,
                error="todo_write requires an active session",
            )
        raw_turn = context.env_vars.get("turn_id")
        turn_id = str(raw_turn or "").strip() or None
        run_id = str(context.env_vars.get("run_id") or "").strip()
        if not run_id:
            return ToolResult(
                success=False,
                error="todo_write requires an active run",
            )
        user_id = str(context.env_vars.get("user_id") or "").strip() or DEFAULT_USER_ID
        raw_items = parameters.get("items")
        if not isinstance(raw_items, list):
            return ToolResult(
                success=False,
                error="todo_write requires 'items' to be a list",
            )
        for raw in raw_items:
            if not isinstance(raw, dict):
                return ToolResult(
                    success=False,
                    error="each todo mutation must be an object",
                )
        try:
            expected_version = int(parameters.get("expected_version"))
        except (TypeError, ValueError):
            return ToolResult(
                success=False,
                error="todo_write requires integer expected_version",
            )

        try:
            store = resolve_control_session_store()
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))
        try:
            async with store.user_content_operation():
                plan = await store.mutate_run_plan(
                    sid,
                    run_id=run_id,
                    plan_id=str(parameters.get("plan_id") or "").strip() or None,
                    expected_version=expected_version,
                    required=(
                        bool(parameters["required"])
                        if "required" in parameters
                        else None
                    ),
                    status=str(parameters.get("status") or "").strip() or None,
                    item_mutations=[dict(item) for item in raw_items],
                )
                logger.info(
                    "todo_write.mutated",
                    session_id=sid,
                    run_id=run_id,
                    plan_id=plan.plan_id,
                    version=plan.version,
                    count=len(plan.items),
                    in_progress=sum(
                        1 for item in plan.items if item.status.value == "in_progress"
                    ),
                )
                await publish_control_todo_state_changed(
                    session_id=sid,
                    user_id=user_id,
                    turn_id=turn_id,
                    plan=plan.to_dict(),
                )
                try:
                    from magi.control.common.events import publish_control_event

                    await publish_control_event(
                        "control.todo.updated",
                        {
                            "session_id": sid,
                            "plan": plan.to_dict(),
                        },
                        session_id=sid,
                        turn_id=turn_id,
                    )
                except Exception:  # pragma: no cover - defensive
                    logger.debug("todo_write.event_failed", exc_info=True)
        except (ControlSessionClearedError, RunPlanError) as exc:
            return ToolResult(success=False, error=str(exc))
        return ToolResult(
            success=True,
            data=plan.to_dict(),
        )


__all__ = ["TodoWriteTool"]
