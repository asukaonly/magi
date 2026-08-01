"""``todo_write`` — manage the session todo list."""

from __future__ import annotations

import uuid
from typing import Any, Dict

from magi.control.common.events import publish_control_todo_state_changed
from magi.control.provider import resolve_control_session_store
from magi.core.logger import get_logger
from magi.identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from magi.control.session_store import ControlSessionClearedError, TodoListError
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
    """Replace the session todo list.

    The full list is replaced in one call — ``items`` is the complete
    desired state. Each item has ``title`` (required) and ``status``
    (``not_started`` / ``in_progress`` / ``completed``; defaults to
    ``not_started``). ``id`` is optional and auto-generated if absent.

    Server-side invariant: at most one item may be ``in_progress``
    at any time. Violations return an error without mutating state.
    """

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="todo_write",
            description=(
                "Replace the session's todo list. Call this to track "
                "progress through multi-step work: add new items, mark "
                "the current one as in_progress, and mark completed ones "
                "as completed. Always send the full list — it replaces "
                "the previous one. At most one item may be in_progress "
                "at a time."
            ),
            category="control",
            parameters=[
                ToolParameter(
                    name="items",
                    type=ParameterType.ARRAY,
                    array_item_type=ParameterType.OBJECT,
                    description=(
                        "The complete todo list. Each item has: title "
                        "(string, required), status (one of: not_started, "
                        "in_progress, completed; optional, defaults to "
                        "not_started), id (string, optional)."
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
        user_id = str(context.env_vars.get("user_id") or "").strip() or DEFAULT_USER_ID
        raw_items = parameters.get("items")
        if not isinstance(raw_items, list):
            return ToolResult(
                success=False,
                error="todo_write requires 'items' to be a list",
            )
        # Inject ids for items that omit them.
        normalised: list[dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                return ToolResult(
                    success=False,
                    error="each todo item must be an object",
                )
            item = dict(raw)
            if not item.get("id"):
                item["id"] = uuid.uuid4().hex
            normalised.append(item)

        try:
            store = resolve_control_session_store()
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))
        try:
            async with store.user_content_operation():
                todos = await store.replace_todos(sid, normalised)
                logger.info(
                    "todo_write.replaced",
                    session_id=sid,
                    count=len(todos),
                    in_progress=sum(
                        1 for t in todos if t.status.value == "in_progress"
                    ),
                )
                await publish_control_todo_state_changed(
                    session_id=sid,
                    user_id=user_id,
                    turn_id=turn_id,
                    items=[t.to_dict() for t in todos],
                )
                try:
                    from magi.control.common.events import publish_control_event

                    await publish_control_event(
                        "control.todo.updated",
                        {
                            "session_id": sid,
                            "items": [t.to_dict() for t in todos],
                        },
                        session_id=sid,
                        turn_id=turn_id,
                    )
                except Exception:  # pragma: no cover - defensive
                    logger.debug("todo_write.event_failed", exc_info=True)
        except (ControlSessionClearedError, TodoListError) as exc:
            return ToolResult(success=False, error=str(exc))
        return ToolResult(
            success=True,
            data={"items": [t.to_dict() for t in todos]},
        )


__all__ = ["TodoWriteTool"]
