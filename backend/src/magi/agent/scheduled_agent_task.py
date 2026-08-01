"""Scheduler integration for user-created agent task schedules."""

from __future__ import annotations

from typing import Any

from ..scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from ..scheduler.service import SchedulerService
from magi_plugin_sdk.run_trigger import RunTrigger

from .background.contracts import BackgroundTaskSpec, BackgroundTaskTriggerSource


def _as_string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace(" ", ",").split(",") if item.strip()]
    return []


def build_background_spec_from_schedule(context: ScheduledExecutionContext) -> BackgroundTaskSpec:
    """Build a background task spec from a user agent task schedule."""
    payload = dict(context.schedule.target_payload or {})
    prompt = _as_string(payload.get("prompt") or payload.get("message") or payload.get("goal"))
    if not prompt:
        raise ValueError("scheduled agent task is missing prompt")
    user_id = _as_string(payload.get("user_id"), "local_user")
    return BackgroundTaskSpec(
        user_id=user_id,
        session_id=_as_string(payload.get("session_id")),
        origin_turn_id=context.schedule.schedule_id,
        title=_as_string(payload.get("title") or context.schedule.metadata.get("display_name"), prompt.splitlines()[0][:80]),
        goal=prompt,
        selected_tools=_as_string_list(payload.get("selected_tools") or payload.get("tools_allow")),
        workspace_path=_as_string(payload.get("workspace_path")) or None,
        trigger_source=BackgroundTaskTriggerSource.SCHEDULE,
        trigger=RunTrigger(
            trigger_type="scheduled",
            source_channel="scheduler",
            requester=user_id,
            priority="background",
            correlation=[context.schedule.schedule_id],
            payload={},
        ),
        max_iterations=int(payload.get("max_iterations") or 50),
        timeout_seconds=(
            int(payload["timeout_seconds"])
            if payload.get("timeout_seconds") is not None
            else 1800
        ),
    )


class UserAgentTaskScheduleContributor:
    """Registers the user-agent-task scheduler handler."""

    def __init__(self, background_task_manager: Any) -> None:
        self._background_task_manager = background_task_manager
        self._scheduler: SchedulerService | None = None

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        self._scheduler = scheduler
        scheduler.register_handler(ScheduledTargetType.USER_AGENT_TASK, self._handle_user_agent_task)

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        _ = scheduler
        self._scheduler = None

    async def _handle_user_agent_task(
        self,
        context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        scheduler = self._scheduler
        if scheduler is None:
            raise RuntimeError("User agent task scheduler is not registered")
        spec = build_background_spec_from_schedule(context)

        async def enqueue() -> Any:
            return await self._background_task_manager.enqueue(spec)

        task = await scheduler.run_user_agent_effect(
            context.data_generation,
            enqueue,
        )
        return ScheduledExecutionResult(
            success=True,
            message="background_task_enqueued",
            stats={"background_task_id": task.task_id},
        )
