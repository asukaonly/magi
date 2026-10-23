"""Reminders converge with current commitments and never resurrect dismissed alerts."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.bootstrap.personal_tasks import PersonalTaskRemindersModule
from magi.notifications.store import NotificationStore
from magi.personal_tasks.models import ItemPatch, TaskMutation


@pytest.fixture
def reminders(personal_service, tmp_path, monkeypatch):
    clock = {"now": 1900000000.0}
    monkeypatch.setattr("magi.personal_tasks.store.time.time", lambda: clock["now"])
    monkeypatch.setattr(
        "magi.bootstrap.personal_tasks._emit_notification_added_signal", AsyncMock()
    )
    module = PersonalTaskRemindersModule(SimpleNamespace())
    module._service = personal_service
    module._notifications = NotificationStore(str(tmp_path / "notifications.db"))
    module._notifications.ensure_schema()
    scheduled = {}

    async def schedule_once(**kwargs):
        scheduled[kwargs["schedule_id"]] = SimpleNamespace(**kwargs)

    async def unschedule(schedule_id):
        scheduled.pop(schedule_id, None)

    module._scheduler = SimpleNamespace(
        schedule_once=AsyncMock(side_effect=schedule_once),
        unschedule=AsyncMock(side_effect=unschedule),
        repository=SimpleNamespace(
            list_schedules=AsyncMock(side_effect=lambda **_: list(scheduled.values()))
        ),
    )
    personal_service.on_changed = module.reconcile
    return module, clock, scheduled


async def create_reminder(service, clock):
    return (
        await service.mutate(
            "local_user",
            TaskMutation(
                request_id="remind",
                action="create",
                fields=ItemPatch(
                    title="Call customer",
                    remind_at=datetime.fromtimestamp(clock["now"] + 60, timezone.utc).isoformat(),
                ),
            ),
            actor="user",
        )
    ).item


@pytest.mark.asyncio
async def test_delivery_is_once_and_delete_removes_dismissed_notification(
    personal_service, reminders
):
    module, clock, scheduled = reminders
    item = await create_reminder(personal_service, clock)
    assert item.reminder_revision == item.reminder_synced_revision
    context = SimpleNamespace(schedule=next(iter(scheduled.values())))
    clock["now"] += 61
    await module._fire(context)
    rows = module._notifications.list_by_kind(user_id="local_user", kind="personal_task_reminder")
    assert len(rows) == 1
    module._notifications.mark_dismissed(rows[0].id, "explicit")
    await module._fire(context)
    assert module._notifications.list_for_user("local_user") == []
    assert (
        len(module._notifications.list_by_kind(user_id="local_user", kind="personal_task_reminder"))
        == 1
    )
    await personal_service.mutate(
        "local_user",
        TaskMutation(
            request_id="delete", action="delete", item_id=item.id, expected_version=item.version
        ),
        actor="user",
    )
    assert not scheduled
    assert (
        module._notifications.list_by_kind(user_id="local_user", kind="personal_task_reminder")
        == []
    )
    assert (await module._fire(context)).message == "personal_item_deleted"


@pytest.mark.asyncio
async def test_retime_completion_and_missed_deadline_do_not_send_old_alerts(
    personal_service, reminders
):
    module, clock, scheduled = reminders
    item = await create_reminder(personal_service, clock)
    old = SimpleNamespace(schedule=next(iter(scheduled.values())))
    changed = (
        await personal_service.mutate(
            "local_user",
            TaskMutation(
                request_id="retime",
                action="update",
                item_id=item.id,
                expected_version=1,
                fields=ItemPatch(
                    remind_at=datetime.fromtimestamp(clock["now"] + 120, timezone.utc).isoformat()
                ),
            ),
            actor="user",
        )
    ).item
    assert len(scheduled) == 1
    assert (await module._fire(old)).message == "personal_reminder_obsolete"
    current = SimpleNamespace(schedule=next(iter(scheduled.values())))
    clock["now"] += 500
    assert (await module._fire(current)).message == "personal_reminder_missed_while_offline"
    assert module._notifications.unread_count("local_user") == 0
    completed = (
        await personal_service.mutate(
            "local_user",
            TaskMutation(
                request_id="complete",
                action="update",
                item_id=item.id,
                expected_version=changed.version,
                fields=ItemPatch(status="completed"),
            ),
            actor="user",
        )
    ).item
    assert completed.remind_at is None and not scheduled


@pytest.mark.asyncio
async def test_registration_failure_stays_pending_and_reconciliation_repairs_it(
    personal_service, reminders
):
    module, clock, scheduled = reminders
    register = module._scheduler.schedule_once.side_effect
    module._scheduler.schedule_once.side_effect = RuntimeError("Scheduler unavailable")
    item = await create_reminder(personal_service, clock)
    assert item.reminder_synced_revision != item.reminder_revision
    module._scheduler.schedule_once.side_effect = register
    await module.reconcile()
    repaired = (await personal_service.store.get("local_user", item.id)).item
    assert repaired.reminder_synced_revision == repaired.reminder_revision and len(scheduled) == 1
