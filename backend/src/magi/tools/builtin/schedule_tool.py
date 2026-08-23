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
            effect_replay_policy="reconcilable",
            parameters=self._schema_parameters(),
            tags=["schedule", "automation", "background", "reminder"],
            timeout=30,
            metadata=self._schema_metadata(),
        )

    def _schema_parameters(self) -> list[ToolParameter]:
        return self._schedule_object_parameters() + self._schedule_option_parameters()

    @staticmethod
    def _schedule_object_parameters() -> list[ToolParameter]:
        return [
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
        ]

    @staticmethod
    def _schedule_option_parameters() -> list[ToolParameter]:
        return [
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
        ]

    @staticmethod
    def _schema_metadata() -> dict[str, Any]:
        return {
            "task_intents": ["schedule_task", "manage_reminder", "automation"],
            "domains": ["automation", "scheduler"],
            "operations": ["list", "create", "update", "delete", "run"],
            "tool_hint": "Use for reminders and recurring agent tasks; do not emulate scheduling with shell sleeps.",
        }

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
                return await self._execute_list(parameters, service)
            if action == "get":
                return await self._execute_get(parameters, service)
            if action == "add":
                return await self._execute_add(parameters, service, actor)
            if action == "update":
                return await self._execute_update(parameters, service, actor)
            if action == "remove":
                return await self._execute_remove(parameters, service)
            if action == "run":
                return await self._execute_run(parameters, service)
            if action == "activity":
                return await self._execute_activity(parameters, service)
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

    async def _execute_list(
        self,
        parameters: Dict[str, Any],
        service: ScheduleManagementService,
    ) -> ToolResult:
        schedules = await service.list_schedules(
            include_disabled=bool(parameters.get("include_disabled", False)),
            include_system=bool(parameters.get("include_system", True)),
        )
        return ToolResult(success=True, data={"schedules": schedules})

    async def _execute_get(
        self,
        parameters: Dict[str, Any],
        service: ScheduleManagementService,
    ) -> ToolResult:
        schedule = await service.get_schedule(self._required_schedule_id(parameters))
        if schedule is None:
            raise ScheduleManagementError("schedule not found")
        return ToolResult(success=True, data={"schedule": schedule})

    async def _execute_add(
        self,
        parameters: Dict[str, Any],
        service: ScheduleManagementService,
        actor: ScheduleActorContext,
    ) -> ToolResult:
        raw_schedule = self._object_payload(parameters, key="schedule")
        if not isinstance(raw_schedule, dict):
            raise ScheduleManagementError("schedule is required")
        schedule = await service.create_user_agent_task_schedule(raw_schedule, actor)
        return ToolResult(success=True, data={"schedule": schedule})

    async def _execute_update(
        self,
        parameters: Dict[str, Any],
        service: ScheduleManagementService,
        actor: ScheduleActorContext,
    ) -> ToolResult:
        patch = self._object_payload(parameters, key="patch")
        if not isinstance(patch, dict):
            raise ScheduleManagementError("patch is required")
        schedule = await service.update_user_schedule(
            self._required_schedule_id(parameters),
            patch,
            actor,
        )
        return ToolResult(success=True, data={"schedule": schedule})

    async def _execute_remove(
        self,
        parameters: Dict[str, Any],
        service: ScheduleManagementService,
    ) -> ToolResult:
        removed = await service.remove_user_schedule(self._required_schedule_id(parameters))
        return ToolResult(success=True, data=removed)

    async def _execute_run(
        self,
        parameters: Dict[str, Any],
        service: ScheduleManagementService,
    ) -> ToolResult:
        result = await service.run_user_schedule(self._required_schedule_id(parameters))
        return ToolResult(success=True, data=result)

    async def _execute_activity(
        self,
        parameters: Dict[str, Any],
        service: ScheduleManagementService,
    ) -> ToolResult:
        schedule_id = self._schedule_id(parameters) or None
        limit = int(parameters.get("limit") or 20)
        activity = await service.list_activity(schedule_id=schedule_id, limit=limit)
        return ToolResult(success=True, data=activity)

    @staticmethod
    def _required_schedule_id(parameters: Dict[str, Any]) -> str:
        schedule_id = ScheduleTool._schedule_id(parameters)
        if not schedule_id:
            raise ScheduleManagementError("schedule_id is required")
        return schedule_id

    @staticmethod
    def _schedule_id(parameters: Dict[str, Any]) -> str:
        return str(parameters.get("schedule_id") or parameters.get("id") or "").strip()

    @staticmethod
    def _object_payload(parameters: Dict[str, Any], *, key: str) -> Any:
        value = parameters.get(key)
        if _is_missing_object(value):
            return _recover_schedule_from_flat_params(dict(parameters))
        return value

    def is_ready(self) -> bool:
        try:
            require_scheduler_service()
        except RuntimeError:
            return False
        return True
