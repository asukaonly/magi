"""Durable commitment lifecycle, version conflicts, and deletion boundaries."""

import asyncio
import json
import sqlite3
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from magi.personal_tasks.models import (
    ItemPatch,
    TaskConflictError,
    TaskMutation,
    TaskNotFoundError,
    TaskReference,
)
from magi.personal_tasks.store import PersonalTaskStore


async def create(service, request="create", **fields):
    return (
        await service.mutate(
            "local_user",
            TaskMutation(
                request_id=request,
                action="create",
                fields=ItemPatch(title="Prepare quote", **fields),
            ),
            actor="user",
        )
    ).item


@pytest.mark.asyncio
async def test_progress_is_atomic_replayable_and_survives_reopen(personal_service):
    item = await create(personal_service, body_md="Budget 50,000. Keep local deployment.")
    command = TaskMutation(
        request_id="waiting",
        action="progress",
        item_id=item.id,
        expected_version=1,
        fields=ItemPatch(status="waiting"),
        note="Waiting for client parameters",
    )
    first = await personal_service.mutate("local_user", command, actor="agent")
    second = await personal_service.mutate("local_user", command, actor="agent")
    assert second.replayed and second.item.version == first.item.version == 2
    reopened = PersonalTaskStore(personal_service.store.db_path)
    detail = await reopened.get("local_user", item.id)
    assert detail.item.status == "waiting" and detail.item.body_md == item.body_md
    assert len(detail.changes) == 2 and detail.changes[0].note == command.note
    assert (await reopened.query("local_user", view="next")).total == 0
    assert (await reopened.query("local_user", view="waiting")).total == 1
    with pytest.raises(TaskConflictError):
        await personal_service.mutate(
            "local_user", command.model_copy(update={"request_id": "stale"}), actor="user"
        )
    with pytest.raises(TaskConflictError):
        await personal_service.mutate(
            "local_user", command.model_copy(update={"note": "Different operation"}), actor="user"
        )


@pytest.mark.asyncio
async def test_concurrent_edits_never_overwrite_each_other(personal_service):
    item = await create(personal_service)

    async def update(key, title):
        return await personal_service.mutate(
            "local_user",
            TaskMutation(
                request_id=key,
                action="update",
                item_id=item.id,
                expected_version=1,
                fields=ItemPatch(title=title),
            ),
            actor="user",
        )

    results = await asyncio.gather(
        update("one", "First edit"), update("two", "Second edit"), return_exceptions=True
    )
    assert sum(isinstance(result, TaskConflictError) for result in results) == 1
    assert (await personal_service.store.get("local_user", item.id)).item.version == 2
    with pytest.raises(TaskNotFoundError):
        await personal_service.store.get("another-user", item.id)


@pytest.mark.asyncio
async def test_next_view_respects_defer_parent_and_literal_search(personal_service):
    project = await create(personal_service, "project", kind="project", status="someday")
    await create(personal_service, "child", parent_id=project.id)
    await create(personal_service, "future", defer_until="2099-01-01", timezone="Asia/Shanghai")
    action = await create(personal_service, "current", body_md="100% user constraints")
    page = await personal_service.store.query("local_user", view="next")
    assert [item.id for item in page.items] == [action.id]
    assert (await personal_service.store.query("local_user", view="all", search="100%")).total == 1
    assert (await personal_service.store.query("local_user", view="all", limit=2)).next_offset == 2
    await personal_service.mutate(
        "local_user",
        TaskMutation(
            request_id="activate",
            action="update",
            item_id=project.id,
            expected_version=1,
            fields=ItemPatch(status="active"),
        ),
        actor="user",
    )
    assert (await personal_service.store.query("local_user", view="next")).total == 2


@pytest.mark.asyncio
async def test_source_acceptance_refresh_and_delete_never_recreate_content(personal_service):
    proposal = dict(
        user_id="local_user",
        source_key="connection/object/key",
        title="Imported candidate",
        body_md="Third-party content",
        references=[TaskReference(kind="memory", id="event")],
    )
    item = (await personal_service.propose(**proposal)).item
    assert item.status == "inbox" and item.origin == "source" and item.remind_at is None
    assert (await personal_service.store.get("local_user", item.id)).changes[0].note == ""
    await personal_service.mutate(
        "local_user",
        TaskMutation(
            request_id="accept",
            action="update",
            item_id=item.id,
            expected_version=1,
            fields=ItemPatch(status="active", body_md="User decision"),
        ),
        actor="user",
    )
    refreshed = await personal_service.propose(**{**proposal, "body_md": "Changed source"})
    assert refreshed.replayed and refreshed.item.body_md == "User decision"
    command = TaskMutation(
        request_id="remove", action="delete", item_id=item.id, expected_version=2
    )
    await personal_service.mutate("local_user", command, actor="user")
    replay = await personal_service.propose(**proposal)
    assert replay.item is None and replay.deleted_ids == [item.id]
    with sqlite3.connect(personal_service.store.db_path) as db:
        rows = db.execute(
            "SELECT note,changes_json,references_json FROM personal_item_changes"
        ).fetchall()
    assert all(not note and references == "[]" for note, _, references in rows)
    assert "Third-party" not in json.dumps(rows) and "User decision" not in json.dumps(rows)


@pytest.mark.asyncio
async def test_project_cascade_is_explicit_and_replay_returns_all_ids(personal_service):
    project = await create(personal_service, "project", kind="project")
    child = await create(personal_service, "child", parent_id=project.id)
    command = TaskMutation(
        request_id="delete-project", action="delete", item_id=project.id, expected_version=1
    )
    with pytest.raises(TaskConflictError):
        await personal_service.mutate("local_user", command, actor="user")
    command.cascade = True
    result = await personal_service.mutate("local_user", command, actor="user")
    replay = await personal_service.mutate("local_user", command, actor="user")
    assert set(result.deleted_ids) == {project.id, child.id}
    assert replay.replayed and replay.deleted_ids == result.deleted_ids
    assert (await personal_service.store.query("local_user", view="all")).total == 0


@pytest.mark.asyncio
async def test_clear_blocks_writes_and_erases_history(personal_service):
    item = await create(personal_service, body_md="Private constraints")
    async with personal_service.user_content_clear_boundary():
        with pytest.raises(RuntimeError, match="paused"):
            await create(personal_service, "late")
        assert await personal_service.store.clear_user_content() == 1
    replay = await personal_service.mutate(
        "local_user",
        TaskMutation(
            request_id="create",
            action="create",
            fields=ItemPatch(title="Prepare quote", body_md="Private constraints"),
        ),
        actor="user",
    )
    assert replay.deleted_ids == [item.id] and replay.item is None
    with sqlite3.connect(personal_service.store.db_path) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM personal_item_changes WHERE note!='' OR changes_json!='{}' OR references_json!='[]'"
            ).fetchone()[0]
            == 0
        )
    assert (await create(personal_service, "after-clear")).version == 1


@pytest.mark.asyncio
async def test_committed_write_is_successful_when_reminder_sync_fails(personal_service):
    personal_service.on_changed = AsyncMock(side_effect=RuntimeError("Scheduler offline"))
    command = TaskMutation(
        request_id="reminder",
        action="create",
        fields=ItemPatch(
            title="Follow up",
            remind_at=datetime.fromtimestamp(time.time() + 3600, timezone.utc).isoformat(),
        ),
    )
    result = await personal_service.mutate("local_user", command, actor="user")
    assert result.reminders_pending and result.item.version == 1
    assert (await personal_service.store.get("local_user", result.item.id)).item.remind_at


@pytest.mark.parametrize(
    "fields",
    [
        {"title": " "},
        {"title": "x", "due": "tomorrow"},
        {"title": "x", "remind_at": "2030-01-01"},
        {"title": "x", "timezone": "Unknown/Zone"},
    ],
)
@pytest.mark.asyncio
async def test_invalid_content_is_not_persisted(personal_service, fields):
    with pytest.raises((ValueError, ValidationError)):
        await personal_service.mutate(
            "local_user",
            TaskMutation(request_id="invalid", action="create", fields=ItemPatch(**fields)),
            actor="user",
        )
    assert (await personal_service.store.query("local_user", view="all")).total == 0


def test_progress_requires_resulting_state():
    with pytest.raises(ValidationError, match="fields.status"):
        TaskMutation(
            request_id="progress",
            action="progress",
            item_id="item",
            expected_version=1,
            note="Waiting for reply",
        )
