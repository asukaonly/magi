"""Wire personal reminders to the existing scheduler and notification center."""

from __future__ import annotations

import asyncio
import json
import time

from ..core.logger import get_logger
from ..identity.defaults import CANONICAL_LOCAL_USER
from ..notifications.service import _emit_notification_added_signal
from ..notifications.store import NotificationRow, get_notification_store
from ..personal_tasks.models import PersonalItem, TaskNotFoundError
from ..personal_tasks.service import get_personal_task_service
from ..personal_tasks.store import time_epoch
from ..scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from .context import RuntimeBootstrapContext, require_initialized
from .lifecycle import LifecycleModule

logger = get_logger(__name__)
_PREFIX = "personal-task:"
_RECONCILE = "personal-task-reconcile"


class PersonalTaskRemindersModule(LifecycleModule):
    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_personal_task_reminders",
            dependencies=("runtime_personal_tasks", "runtime_scheduler", "runtime_trace"),
        )
        self._context = context
        self._sync_lock = asyncio.Lock()

    async def init(self) -> None:
        self._scheduler = require_initialized(
            self._context.scheduler.scheduler_service, "scheduler"
        )
        self._service = get_personal_task_service()
        self._notifications = get_notification_store()
        self._scheduler.register_handler(ScheduledTargetType.PERSONAL_TASK_REMINDER, self._fire)
        self._scheduler.register_handler(
            ScheduledTargetType.PERSONAL_TASK_RECONCILE, self._reconcile_tick
        )
        if self._context.runtime_commands.full_clear_recovery_pending:
            return
        await self.reconcile()
        await self._scheduler.schedule_interval(
            schedule_id=_RECONCILE,
            target_type=ScheduledTargetType.PERSONAL_TASK_RECONCILE,
            target_key=_RECONCILE,
            seconds=60,
            target_payload={},
            metadata={"owner_kind": "system"},
        )
        self._service.on_changed = self.reconcile

    async def shutdown(self) -> None:
        self._service.on_changed = None

    async def _eligible(self, item: PersonalItem) -> bool:
        if item.status not in {"active", "waiting"} or item.remind_at is None:
            return False
        if item.parent_id:
            try:
                parent = (await self._service.store.get(item.user_id, item.parent_id)).item
            except TaskNotFoundError:
                return False
            if parent.status != "active":
                return False
        return True

    async def reconcile(self) -> None:
        """Repair desired reminders after commits or crashes without a second queue."""
        async with self._sync_lock, self._service.lock:
            items = {item.id: item for item in await self._service.store.reminder_items()}
            schedules = {
                s.schedule_id: s
                for s in await self._scheduler.repository.list_schedules(enabled_only=False)
                if s.target_type is ScheduledTargetType.PERSONAL_TASK_REMINDER
            }
            for schedule_id, schedule in schedules.items():
                item = items.get(schedule.target_key)
                if (
                    item is None
                    or not await self._eligible(item)
                    or schedule.target_payload.get("revision") != item.reminder_revision
                ):
                    await self._scheduler.unschedule(schedule_id)
            for item in items.values():
                run_at = time_epoch(item.remind_at, item.timezone)
                if (
                    await self._eligible(item)
                    and run_at
                    and run_at > time.time()
                    and item.reminder_delivered_revision != item.reminder_revision
                ):
                    schedule_id = f"{_PREFIX}{item.id}:{item.reminder_revision}"
                    if schedule_id not in schedules:
                        try:
                            await self._scheduler.schedule_once(
                                schedule_id=schedule_id,
                                target_type=ScheduledTargetType.PERSONAL_TASK_REMINDER,
                                target_key=item.id,
                                run_at=run_at,
                                target_payload={
                                    "user_id": item.user_id,
                                    "item_id": item.id,
                                    "revision": item.reminder_revision,
                                },
                                metadata={"owner_kind": "personal_task"},
                            )
                        except Exception:
                            logger.warning(
                                "Personal reminder registration remains pending",
                                item_id=item.id,
                                exc_info=True,
                            )
                            continue
                await self._service.store.mark_reminder(item)
            notifications = await asyncio.to_thread(
                self._notifications.list_by_kind,
                user_id=str(CANONICAL_LOCAL_USER),
                kind="personal_task_reminder",
            )
            for notification in notifications:
                if notification.kind != "personal_task_reminder":
                    continue
                payload = json.loads(notification.payload_json)
                try:
                    item = (
                        await self._service.store.get(
                            notification.user_id, str(payload.get("personal_item_id", ""))
                        )
                    ).item
                    obsolete = not await self._eligible(
                        item
                    ) or item.reminder_revision != payload.get("revision")
                except TaskNotFoundError:
                    obsolete = True
                if obsolete:
                    await asyncio.to_thread(
                        self._notifications.delete_by_dedupe,
                        user_id=notification.user_id,
                        kind=notification.kind,
                        dedupe_key=notification.dedupe_key,
                    )

    async def _reconcile_tick(self, context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        await self.reconcile()
        return ScheduledExecutionResult(success=True)

    async def _fire(self, context: ScheduledExecutionContext) -> ScheduledExecutionResult:
        payload = context.schedule.target_payload
        async with self._service.lock:
            try:
                item = (
                    await self._service.store.get(str(payload["user_id"]), str(payload["item_id"]))
                ).item
            except TaskNotFoundError:
                return ScheduledExecutionResult(success=True, message="personal_item_deleted")
            if item.reminder_revision != payload.get("revision") or not await self._eligible(item):
                return ScheduledExecutionResult(success=True, message="personal_reminder_obsolete")
            if item.reminder_delivered_revision == item.reminder_revision:
                return ScheduledExecutionResult(
                    success=True, message="personal_reminder_already_delivered"
                )
            due = time_epoch(item.remind_at, item.timezone)
            if due is None or time.time() < due:
                return ScheduledExecutionResult(success=True, message="personal_reminder_not_due")
            if time.time() - due > 300:
                return ScheduledExecutionResult(
                    success=True, message="personal_reminder_missed_while_offline"
                )
            await asyncio.to_thread(
                self._notifications.insert_once,
                NotificationRow(
                    user_id=item.user_id,
                    kind="personal_task_reminder",
                    dedupe_key=f"{_PREFIX}{item.id}:{item.reminder_revision}",
                    title=item.title,
                    body=item.title,
                    payload_json=json.dumps(
                        {"personal_item_id": item.id, "revision": item.reminder_revision}
                    ),
                ),
            )
            await self._service.store.mark_reminder(item, delivered=True)
        await _emit_notification_added_signal(
            user_id=item.user_id,
            unread_count=await asyncio.to_thread(self._notifications.unread_count, item.user_id),
        )
        return ScheduledExecutionResult(success=True, message="personal_reminder_delivered")
