"""Agent-callable scheduling tool."""

from __future__ import annotations

from typing import Any, Dict

from ...core.runtime_bindings import require_scheduler_service
from ...scheduler.management import (
    ScheduleActorContext,
    ScheduleManagementError,
    ScheduleManagementService,
    SchedulePermissionError,
)
from ..schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)


SCHEDULE_ACTIONS = ["list", "get", "add", "update", "remove", "run", "activity"]


def _is_missing_object(value: Any) -> bool:
    return not isinstance(value, dict) or not value


def _recover_schedule_from_flat_params(parameters: dict[str, Any]) -> dict[str, Any] | None:
    keys = {
        "schedule_id",
        "id",
        "title",
        "name",
        "trigger",
        "trigger_type",
        "type",
        "kind",
        "run_at",
        "at",
        "seconds",
        "interval_seconds",
        "every_seconds",
        "cron",
        "expr",
        "timezone",
        "tz",
        "target",
        "prompt",
        "message",
        "goal",
        "tools_allow",
        "selected_tools",
        "timeout_seconds",
        "max_iterations",
        "workspace_path",
        "enabled",
    }
    recovered = {key: parameters[key] for key in keys if key in parameters and parameters[key] is not None}
    return recovered or None


class ScheduleTool(Tool):
    """Manage user-created schedules from an agent turn."""

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="schedule",
            description=(
                "Manage scheduler jobs for reminders and recurring agent tasks. "
                "Use this instead of shell sleep loops or polling. Actions: list/get/add/update/remove/run/activity. "
                "The first version can create only target.kind='agent_task', which enqueues a background agent task when fired. "
                "System-owned schedules can be listed, but only agent-created schedules can be updated, removed, or run. "
                "For add/update, prefer schedule={trigger:{trigger_type:'once|interval|cron', config:{...}}, "
                "target:{kind:'agent_task', prompt:'...', tools_allow:[...]}}. Flat fields like run_at, cron, prompt, "
                "and tools_allow are also accepted. Interval schedules must be at least 60 seconds."
            ),
            category="automation",
            parameters=[
                ToolParameter(
                    name="action",
                    type=ParameterType.STRING,
                    description="Action to perform: list, get, add, update, remove, run, or activity.",
                    required=True,
                    enum=SCHEDULE_ACTIONS,
                ),
                ToolParameter(
                    name="schedule_id",
                    type=ParameterType.STRING,
                    description="Schedule id for get/update/remove/run/activity.",
                    required=False,
                ),
                ToolParameter(
                    name="schedule",
                    type=ParameterType.OBJECT,
                    description="Schedule object for add. Contains trigger, target, title/name, and enabled.",
                    required=False,
                ),
                ToolParameter(
                    name="patch",
                    type=ParameterType.OBJECT,
                    description="Patch object for update. Supports trigger, target prompt/tools, title/name, and enabled.",
                    required=False,
                ),
                ToolParameter(
                    name="include_disabled",
                    type=ParameterType.BOOLEAN,
                    description="Whether list includes disabled schedules.",
                    required=False,
                    default=False,
                ),
                ToolParameter(
                    name="include_system",
                    type=ParameterType.BOOLEAN,
                    description="Whether list includes system-owned schedules as read-only context.",
                    required=False,
                    default=True,
                ),
                ToolParameter(
                    name="limit",
                    type=ParameterType.INTEGER,
                    description="Maximum execution rows for activity.",
                    required=False,
                    default=20,
                    min_value=1,
                    max_value=100,
                ),
            ],
            tags=["schedule", "automation", "background", "reminder"],
            timeout=30,
            metadata={
                "task_intents": ["schedule_task", "manage_reminder", "automation"],
                "domains": ["automation", "scheduler"],
                "operations": ["list", "create", "update", "delete", "run"],
                "tool_hint": "Use for reminders and recurring agent tasks; do not emulate scheduling with shell sleeps.",
            },
        )

    def _service(self) -> ScheduleManagementService:
        return ScheduleManagementService(require_scheduler_service())

    @staticmethod
    def _actor_context(context: ToolExecutionContext) -> ScheduleActorContext:
        return ScheduleActorContext(
            agent_id=context.agent_id,
            user_id=context.env_vars.get("user_id") or "local_user",
            session_id=context.env_vars.get("session_id") or context.task_id or "",
            workspace_path=context.workspace,
        )

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        action = str(parameters.get("action") or "").strip()
        service = self._service()
        actor = self._actor_context(context)
        try:
            if action == "list":
                schedules = await service.list_schedules(
                    include_disabled=bool(parameters.get("include_disabled", False)),
                    include_system=bool(parameters.get("include_system", True)),
                )
                return ToolResult(success=True, data={"schedules": schedules})

            if action == "get":
                schedule_id = str(parameters.get("schedule_id") or parameters.get("id") or "").strip()
                if not schedule_id:
                    raise ScheduleManagementError("schedule_id is required")
                schedule = await service.get_schedule(schedule_id)
                if schedule is None:
                    raise ScheduleManagementError("schedule not found")
                return ToolResult(success=True, data={"schedule": schedule})

            if action == "add":
                raw_schedule = parameters.get("schedule")
                if _is_missing_object(raw_schedule):
                    raw_schedule = _recover_schedule_from_flat_params(dict(parameters))
                if not isinstance(raw_schedule, dict):
                    raise ScheduleManagementError("schedule is required")
                schedule = await service.create_user_agent_task_schedule(raw_schedule, actor)
                return ToolResult(success=True, data={"schedule": schedule})

            if action == "update":
                schedule_id = str(parameters.get("schedule_id") or parameters.get("id") or "").strip()
                if not schedule_id:
                    raise ScheduleManagementError("schedule_id is required")
                patch = parameters.get("patch")
                if _is_missing_object(patch):
                    patch = _recover_schedule_from_flat_params(dict(parameters))
                if not isinstance(patch, dict):
                    raise ScheduleManagementError("patch is required")
                schedule = await service.update_user_schedule(schedule_id, patch, actor)
                return ToolResult(success=True, data={"schedule": schedule})

            if action == "remove":
                schedule_id = str(parameters.get("schedule_id") or parameters.get("id") or "").strip()
                if not schedule_id:
                    raise ScheduleManagementError("schedule_id is required")
                removed = await service.remove_user_schedule(schedule_id)
                return ToolResult(success=True, data=removed)

            if action == "run":
                schedule_id = str(parameters.get("schedule_id") or parameters.get("id") or "").strip()
                if not schedule_id:
                    raise ScheduleManagementError("schedule_id is required")
                result = await service.run_user_schedule(schedule_id)
                return ToolResult(success=True, data=result)

            if action == "activity":
                schedule_id = str(parameters.get("schedule_id") or parameters.get("id") or "").strip() or None
                limit = int(parameters.get("limit") or 20)
                return ToolResult(success=True, data=await service.list_activity(schedule_id=schedule_id, limit=limit))

            return ToolResult(
                success=False,
                error=f"Unsupported schedule action: {action}",
                error_code=ToolErrorCode.INVALID_ACTION.value,
            )
        except SchedulePermissionError as exc:
            return ToolResult(success=False, error=str(exc), error_code=ToolErrorCode.PERMISSION_DENIED.value)
        except ScheduleManagementError as exc:
            return ToolResult(success=False, error=str(exc), error_code=ToolErrorCode.INVALID_PARAMETERS.value)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc), error_code=ToolErrorCode.EXECUTION_ERROR.value)

    def is_ready(self) -> bool:
        try:
            require_scheduler_service()
        except RuntimeError:
            return False
        return True
