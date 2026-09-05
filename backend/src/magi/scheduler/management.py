"""Management helpers for user-created scheduler definitions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .contracts import (
    ScheduleDefinition,
    ScheduledTargetState,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)
from .repository import ScheduleRepository
from .service import SchedulerService

USER_SCHEDULE_OWNER_KIND = "agent_created"
USER_AGENT_TARGET_KIND = "agent_task"
MIN_INTERVAL_SECONDS = 60.0
DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_MAX_ITERATIONS = 50
MAX_PROMPT_LENGTH = 16000


class ScheduleManagementError(ValueError):
    """Raised when a user schedule request is invalid."""


class SchedulePermissionError(PermissionError):
    """Raised when a request tries to mutate a non-user schedule."""


@dataclass(slots=True)
class ScheduleActorContext:
    """Actor metadata copied into agent-created schedules."""

    agent_id: str = "agent"
    user_id: str = "local_user"
    session_id: str = ""
    workspace_path: str | None = None


def _string_value(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _finite_float(value: Any, *, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ScheduleManagementError(f"{field_name} must be a finite number") from exc
    if not number == number or number in (float("inf"), float("-inf")):
        raise ScheduleManagementError(f"{field_name} must be a finite number")
    return number


def _optional_positive_int(value: Any, *, field_name: str, default: int) -> int:
    if value is None:
        return default
    number = int(_finite_float(value, field_name=field_name))
    if number < 1:
        raise ScheduleManagementError(f"{field_name} must be >= 1")
    return number


def _parse_run_at(value: Any) -> float:
    if isinstance(value, (int, float)):
        return _finite_float(value, field_name="run_at")
    text = _string_value(value)
    if not text:
        raise ScheduleManagementError("run_at is required for once schedules")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ScheduleManagementError("run_at must be a Unix timestamp or ISO-8601 datetime") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _cron_config_from_expression(expr: str, timezone_name: str | None = None) -> dict[str, Any]:
    parts = [part for part in expr.split() if part]
    if len(parts) == 5:
        minute, hour, day, month, day_of_week = parts
        config: dict[str, Any] = {
            "minute": minute,
            "hour": hour,
            "day": day,
            "month": month,
            "day_of_week": day_of_week,
        }
    elif len(parts) == 6:
        second, minute, hour, day, month, day_of_week = parts
        config = {
            "second": second,
            "minute": minute,
            "hour": hour,
            "day": day,
            "month": month,
            "day_of_week": day_of_week,
        }
    else:
        raise ScheduleManagementError("cron expression must have 5 or 6 fields")
    if timezone_name:
        config["timezone"] = timezone_name
    return config


def _normalize_trigger(raw: dict[str, Any]) -> TriggerDefinition:
    trigger_raw = raw.get("trigger") if isinstance(raw.get("trigger"), dict) else {}
    trigger_type_raw = (
        trigger_raw.get("trigger_type")
        or trigger_raw.get("type")
        or trigger_raw.get("kind")
        or raw.get("trigger_type")
        or raw.get("type")
        or raw.get("schedule_kind")
    )
    if not trigger_type_raw:
        if raw.get("run_at") is not None or raw.get("at") is not None:
            trigger_type_raw = TriggerType.ONCE.value
        elif raw.get("seconds") is not None or raw.get("interval_seconds") is not None or raw.get("every_seconds") is not None:
            trigger_type_raw = TriggerType.INTERVAL.value
        elif raw.get("cron") is not None or raw.get("expr") is not None:
            trigger_type_raw = TriggerType.CRON.value
    try:
        trigger_type = TriggerType(str(trigger_type_raw or ""))
    except ValueError as exc:
        raise ScheduleManagementError("trigger type must be one of once, interval, cron") from exc

    config_raw = trigger_raw.get("config") if isinstance(trigger_raw.get("config"), dict) else {}
    if trigger_type is TriggerType.ONCE:
        run_at = (
            config_raw.get("run_at")
            or trigger_raw.get("run_at")
            or trigger_raw.get("at")
            or raw.get("run_at")
            or raw.get("at")
        )
        return TriggerDefinition(trigger_type, {"run_at": _parse_run_at(run_at)})

    if trigger_type is TriggerType.INTERVAL:
        seconds_value = (
            config_raw.get("seconds")
            or trigger_raw.get("seconds")
            or trigger_raw.get("interval_seconds")
            or raw.get("seconds")
            or raw.get("interval_seconds")
            or raw.get("every_seconds")
        )
        seconds = _finite_float(seconds_value, field_name="seconds")
        if seconds < MIN_INTERVAL_SECONDS:
            raise ScheduleManagementError(f"interval schedules must be at least {int(MIN_INTERVAL_SECONDS)} seconds")
        return TriggerDefinition(trigger_type, {"seconds": seconds})

    cron_expr = config_raw.get("expr") or config_raw.get("cron") or trigger_raw.get("expr") or trigger_raw.get("cron") or raw.get("expr") or raw.get("cron")
    timezone_name = _string_value(
        config_raw.get("timezone") or config_raw.get("tz") or trigger_raw.get("timezone") or trigger_raw.get("tz") or raw.get("timezone") or raw.get("tz"),
        default="",
    )
    if cron_expr:
        return TriggerDefinition(trigger_type, _cron_config_from_expression(str(cron_expr).strip(), timezone_name or None))
    config = dict(config_raw or trigger_raw.get("config") or {})
    if not config:
        for key in ("year", "month", "day", "week", "day_of_week", "hour", "minute", "second", "start_date", "end_date", "timezone", "jitter"):
            if raw.get(key) is not None:
                config[key] = raw[key]
    if timezone_name and "timezone" not in config:
        config["timezone"] = timezone_name
    if not config:
        raise ScheduleManagementError("cron schedules require expr/cron or cron field config")
    return TriggerDefinition(trigger_type, config)


def _normalize_tools(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.replace(" ", ",").split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ScheduleManagementError("tools_allow must be an array or comma-separated string")


def _normalize_target(raw: dict[str, Any], actor: ScheduleActorContext, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    target_raw = raw.get("target") if isinstance(raw.get("target"), dict) else {}
    merged = dict(existing or {})
    merged.update(target_raw)
    for key in ("kind", "prompt", "message", "goal", "title", "tools_allow", "selected_tools", "timeout_seconds", "max_iterations", "workspace_path", "user_id", "session_id"):
        if raw.get(key) is not None:
            merged[key] = raw[key]
    kind = _string_value(merged.get("kind"), USER_AGENT_TARGET_KIND)
    if kind != USER_AGENT_TARGET_KIND:
        raise ScheduleManagementError("target.kind currently supports only agent_task")
    prompt = _string_value(merged.get("prompt") or merged.get("message") or merged.get("goal"))
    if not prompt:
        raise ScheduleManagementError("target.prompt is required")
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise ScheduleManagementError(f"target.prompt must be <= {MAX_PROMPT_LENGTH} characters")
    selected_tools = _normalize_tools(merged.get("tools_allow") if merged.get("tools_allow") is not None else merged.get("selected_tools"))
    return {
        "kind": USER_AGENT_TARGET_KIND,
        "prompt": prompt,
        "title": _string_value(merged.get("title") or raw.get("title") or raw.get("name"), prompt.splitlines()[0][:80]),
        "selected_tools": selected_tools,
        "workspace_path": _string_value(merged.get("workspace_path"), actor.workspace_path or "") or None,
        "user_id": _string_value(merged.get("user_id"), actor.user_id),
        "session_id": _string_value(merged.get("session_id"), actor.session_id),
        "timeout_seconds": _optional_positive_int(merged.get("timeout_seconds"), field_name="timeout_seconds", default=DEFAULT_TIMEOUT_SECONDS),
        "max_iterations": _optional_positive_int(merged.get("max_iterations"), field_name="max_iterations", default=DEFAULT_MAX_ITERATIONS),
    }


def serialize_schedule(schedule: ScheduleDefinition, state: ScheduledTargetState | None = None) -> dict[str, Any]:
    metadata = dict(schedule.metadata or {})
    owner_kind = metadata.get("owner_kind")
    if schedule.target_type is ScheduledTargetType.SOURCE_SYNC:
        owner_kind = "source_settings"
    elif schedule.target_type is ScheduledTargetType.USER_AGENT_TASK:
        owner_kind = USER_SCHEDULE_OWNER_KIND
    else:
        owner_kind = owner_kind or "system"
    return {
        "schedule_id": schedule.schedule_id,
        "target_type": schedule.target_type.value,
        "target_key": schedule.target_key,
        "trigger": {
            "trigger_type": schedule.trigger.trigger_type.value,
            "config": dict(schedule.trigger.config),
        },
        "target_payload": dict(schedule.target_payload or {}),
        "enabled": schedule.enabled,
        "metadata": metadata,
        "job_id": schedule.job_id,
        "editable": schedule.target_type is ScheduledTargetType.USER_AGENT_TASK,
        "owner_kind": owner_kind,
        "target_state": {
            "target_type": state.target_type.value,
            "target_key": state.target_key,
            "running": state.running,
            "last_run_at": state.last_run_at,
            "last_success_at": state.last_success_at,
            "last_error": state.last_error,
            "last_cursor": state.last_cursor,
            "watermark_ts": state.watermark_ts,
            "next_run_at": state.next_run_at,
            "scheduler_job_id": state.scheduler_job_id,
            "updated_at": state.updated_at,
            "stats": state.stats,
        } if state is not None else None,
    }


class ScheduleManagementService:
    """Create and mutate user-owned schedule definitions."""

    def __init__(self, scheduler_service: SchedulerService) -> None:
        self._scheduler = scheduler_service

    @property
    def repository(self) -> ScheduleRepository:
        return self._scheduler.repository

    async def list_schedules(self, *, include_disabled: bool = False, include_system: bool = True) -> list[dict[str, Any]]:
        await self.repository.initialize()
        schedules = await self.repository.list_schedules(enabled_only=not include_disabled)
        items: list[dict[str, Any]] = []
        for schedule in schedules:
            if not include_system and schedule.target_type is not ScheduledTargetType.USER_AGENT_TASK:
                continue
            # Use get_schedule_runtime_state to populate next_run_at from jobstore (#89).
            state = await self.repository.get_schedule_runtime_state(schedule)
            items.append(serialize_schedule(schedule, state))
        return items

    async def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        await self.repository.initialize()
        schedule = await self.repository.get_schedule(schedule_id)
        if schedule is None:
            return None
        # Use get_schedule_runtime_state to populate next_run_at from jobstore (#89).
        state = await self.repository.get_schedule_runtime_state(schedule)
        return serialize_schedule(schedule, state)

    async def create_user_agent_task_schedule(self, raw: dict[str, Any], actor: ScheduleActorContext) -> dict[str, Any]:
        title = _string_value(raw.get("title") or raw.get("name"), "Scheduled agent task")[:120]
        trigger = _normalize_trigger(raw)
        target_payload = _normalize_target({**raw, "title": title}, actor)
        schedule_id = _string_value(raw.get("schedule_id") or raw.get("id")) or f"agent-task:{uuid4().hex[:16]}"
        if not schedule_id.startswith("agent-task:"):
            schedule_id = f"agent-task:{schedule_id}"
        definition = ScheduleDefinition(
            schedule_id=schedule_id,
            target_type=ScheduledTargetType.USER_AGENT_TASK,
            target_key=schedule_id,
            trigger=trigger,
            target_payload=target_payload,
            enabled=bool(raw.get("enabled", True)),
            metadata={
                "owner_kind": USER_SCHEDULE_OWNER_KIND,
                "target_kind": USER_AGENT_TARGET_KIND,
                "display_name": title,
                "created_by_agent": actor.agent_id,
                "user_id": actor.user_id,
                "session_id": actor.session_id,
            },
        )
        saved = await self._scheduler.schedule(definition)
        # Use get_schedule_runtime_state to populate next_run_at from jobstore (#89).
        state = await self.repository.get_schedule_runtime_state(saved)
        return serialize_schedule(saved, state)

    async def update_user_schedule(self, schedule_id: str, raw_patch: dict[str, Any], actor: ScheduleActorContext) -> dict[str, Any]:
        await self.repository.initialize()
        existing = await self.repository.get_schedule(schedule_id)
        if existing is None:
            raise ScheduleManagementError("schedule not found")
        if existing.target_type is not ScheduledTargetType.USER_AGENT_TASK:
            raise SchedulePermissionError("only agent-created schedules can be modified by this tool")
        patch = raw_patch.get("schedule") if isinstance(raw_patch.get("schedule"), dict) else raw_patch
        trigger = _normalize_trigger(patch) if any(key in patch for key in ("trigger", "trigger_type", "type", "schedule_kind", "run_at", "at", "seconds", "interval_seconds", "every_seconds", "cron", "expr")) else existing.trigger
        target_payload = (
            _normalize_target(patch, actor, existing=dict(existing.target_payload or {}))
            if any(key in patch for key in ("target", "prompt", "message", "goal", "tools_allow", "selected_tools", "timeout_seconds", "max_iterations", "workspace_path"))
            else dict(existing.target_payload or {})
        )
        metadata = dict(existing.metadata or {})
        title = _string_value(patch.get("title") or patch.get("name"))
        if title:
            metadata["display_name"] = title[:120]
            target_payload["title"] = title[:120]
        next_schedule = ScheduleDefinition(
            schedule_id=existing.schedule_id,
            target_type=existing.target_type,
            target_key=existing.target_key,
            trigger=trigger,
            target_payload=target_payload,
            enabled=bool(patch.get("enabled")) if patch.get("enabled") is not None else existing.enabled,
            metadata=metadata,
            job_id=existing.job_id,
        )
        saved = await self._scheduler.schedule(next_schedule)
        # Use get_schedule_runtime_state to populate next_run_at from jobstore (#89).
        state = await self.repository.get_schedule_runtime_state(saved)
        return serialize_schedule(saved, state)

    async def remove_user_schedule(self, schedule_id: str) -> dict[str, Any]:
        await self.repository.initialize()
        existing = await self.repository.get_schedule(schedule_id)
        if existing is None:
            raise ScheduleManagementError("schedule not found")
        if existing.target_type is not ScheduledTargetType.USER_AGENT_TASK:
            raise SchedulePermissionError("only agent-created schedules can be removed by this tool")
        await self._scheduler.unschedule(schedule_id)
        return {"removed": True, "schedule_id": schedule_id}

    async def run_user_schedule(self, schedule_id: str) -> dict[str, Any]:
        await self.repository.initialize()
        existing = await self.repository.get_schedule(schedule_id)
        if existing is None:
            raise ScheduleManagementError("schedule not found")
        if existing.target_type is not ScheduledTargetType.USER_AGENT_TASK:
            raise SchedulePermissionError("only agent-created schedules can be run by this tool")
        result = await self._scheduler.execute_schedule(schedule_id, manual=True)
        return {"schedule_id": schedule_id, "result": asdict(result)}

    async def list_activity(self, *, schedule_id: str | None = None, limit: int = 20) -> dict[str, Any]:
        await self.repository.initialize()
        return {
            "executions": await self.repository.list_executions(
                schedule_id=schedule_id,
                limit=max(1, min(int(limit), 100)),
            )
        }
