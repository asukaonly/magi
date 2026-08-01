"""``enter_plan_mode`` and ``exit_plan_mode`` builtin tools.

While plan mode is active the permission gateway's ``plan_mode_guard``
filters every outgoing tool call against a read-only allowlist, so
the LLM can safely explore and think before committing to actions.
"""

from __future__ import annotations

from typing import Any, Dict

from magi.control.common.events import publish_control_plan_state_changed
from magi.control.provider import resolve_control_session_store
from magi.control.session_store import ControlSessionClearedError
from magi.core.logger import get_logger
from magi.identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from magi_plugin_sdk.tools import (
    ParameterType,
    Tool,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

logger = get_logger(__name__)


def _session_id(context: ToolExecutionContext) -> str | None:
    raw = context.env_vars.get("session_id")
    if not raw:
        return None
    value = str(raw).strip()
    return value or None


def _turn_id(context: ToolExecutionContext) -> str | None:
    raw = context.env_vars.get("turn_id")
    if not raw:
        return None
    value = str(raw).strip()
    return value or None


def _user_id(context: ToolExecutionContext) -> str:
    raw = context.env_vars.get("user_id")
    value = str(raw or "").strip()
    return value or DEFAULT_USER_ID


class EnterPlanModeTool(Tool):
    """Enter read-only planning mode for the current session."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="enter_plan_mode",
            description=(
                "Enter plan mode. While plan mode is active only read-only "
                "tools (file_read, glob, grep, memory_query, web_search, "
                "web_fetch) and the plan-mode tools themselves may run. "
                "Use this when you need to think, read, and outline a "
                "multi-step plan before executing any writes. Call "
                "exit_plan_mode once the plan is ready to present."
            ),
            category="control",
            parameters=[],
            tags=["control", "plan"],
            timeout=5,
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        sid = _session_id(context)
        if sid is None:
            return ToolResult(
                success=False,
                error="enter_plan_mode requires an active session",
            )
        try:
            store = resolve_control_session_store()
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))
        try:
            async with store.user_content_operation():
                state = await store.enter_plan_mode(sid)
                logger.info("plan_mode.entered", session_id=sid)
                await publish_control_plan_state_changed(
                    session_id=sid,
                    user_id=_user_id(context),
                    turn_id=_turn_id(context),
                    state=state.to_dict(),
                )
                await _emit_plan_event(
                    sid,
                    state.to_dict(),
                    turn_id=_turn_id(context),
                )
        except ControlSessionClearedError as exc:
            return ToolResult(success=False, error=str(exc))
        return ToolResult(success=True, data=state.to_dict())


class ExitPlanModeTool(Tool):
    """Exit planning mode, optionally presenting the authored plan."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="exit_plan_mode",
            description=(
                "Exit plan mode and present the plan authored during "
                "planning. Pass the full plan text (markdown supported) "
                "so the UI can render it. After this call, execution "
                "tools become available again."
            ),
            category="control",
            parameters=[
                ToolParameter(
                    name="plan",
                    type=ParameterType.STRING,
                    description="The plan text in markdown.",
                    required=True,
                ),
            ],
            tags=["control", "plan"],
            timeout=5,
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        sid = _session_id(context)
        if sid is None:
            return ToolResult(
                success=False,
                error="exit_plan_mode requires an active session",
            )
        plan_text = str(parameters.get("plan") or "").strip()
        if not plan_text:
            return ToolResult(
                success=False,
                error="exit_plan_mode requires a non-empty 'plan'",
            )
        try:
            store = resolve_control_session_store()
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))
        try:
            async with store.user_content_operation():
                state = await store.exit_plan_mode(sid, plan_text=plan_text)
                logger.info(
                    "plan_mode.exited",
                    session_id=sid,
                    plan_length=len(plan_text),
                )
                await publish_control_plan_state_changed(
                    session_id=sid,
                    user_id=_user_id(context),
                    turn_id=_turn_id(context),
                    state=state.to_dict(),
                )
                await _emit_plan_event(
                    sid,
                    state.to_dict(),
                    turn_id=_turn_id(context),
                )
        except ControlSessionClearedError as exc:
            return ToolResult(success=False, error=str(exc))
        return ToolResult(success=True, data=state.to_dict())


async def _emit_plan_event(
    session_id: str,
    state: Dict[str, Any],
    *,
    turn_id: str | None = None,
) -> None:
    try:
        from magi.control.common.events import publish_control_event

        await publish_control_event(
            "control.plan.updated",
            {"session_id": session_id, "plan": state},
            session_id=session_id,
            turn_id=turn_id,
        )
    except Exception:  # pragma: no cover - defensive
        logger.debug("plan_mode.event_failed", exc_info=True)


__all__ = ["EnterPlanModeTool", "ExitPlanModeTool"]
