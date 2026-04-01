"""Tests for the task (todo) system — store and API."""
from __future__ import annotations

import pytest

from magi.tasks.models import TaskPriority, TaskStatus, UserTask
from magi.tasks.store import TaskStore


class TestUserTaskModel:
    def test_to_dict(self):
        task = UserTask(
            task_id="t1",
            title="Buy milk",
            description="2% organic",
            status=TaskStatus.OPEN,
            priority=TaskPriority.HIGH,
            tags=["grocery"],
            user_id="u1",
            created_at=1000.0,
            updated_at=1000.0,
        )
        d = task.to_dict()
        assert d["task_id"] == "t1"
        assert d["status"] == "open"
        assert d["priority"] == "high"
        assert d["tags"] == ["grocery"]

    def test_defaults(self):
        task = UserTask(task_id="t2", title="Test")
        assert task.status is TaskStatus.OPEN
        assert task.priority is TaskPriority.MEDIUM
        assert task.tags == []
        assert task.created_by == "user"


class TestTaskStore:
    @pytest.fixture
    def store(self, tmp_path):
        return TaskStore(db_path=str(tmp_path / "tasks.db"))

    @pytest.mark.asyncio
    async def test_create_and_get(self, store):
        task = UserTask(task_id="", title="Read docs", user_id="u1")
        created = await store.create_task(task)
        assert created.task_id.startswith("task_")
        assert created.created_at > 0

        fetched = await store.get_task(created.task_id)
        assert fetched is not None
        assert fetched.title == "Read docs"
        assert fetched.user_id == "u1"

    @pytest.mark.asyncio
    async def test_list_by_user(self, store):
        await store.create_task(UserTask(task_id="", title="A", user_id="u1"))
        await store.create_task(UserTask(task_id="", title="B", user_id="u2"))
        await store.create_task(UserTask(task_id="", title="C", user_id="u1"))

        tasks = await store.list_tasks(user_id="u1")
        assert len(tasks) == 2
        titles = {t.title for t in tasks}
        assert titles == {"A", "C"}

    @pytest.mark.asyncio
    async def test_list_by_status(self, store):
        await store.create_task(
            UserTask(task_id="", title="Open", user_id="u1", status=TaskStatus.OPEN)
        )
        await store.create_task(
            UserTask(task_id="", title="Done", user_id="u1", status=TaskStatus.DONE)
        )

        open_tasks = await store.list_tasks(user_id="u1", status="open")
        assert len(open_tasks) == 1
        assert open_tasks[0].title == "Open"

    @pytest.mark.asyncio
    async def test_update_task(self, store):
        created = await store.create_task(
            UserTask(task_id="", title="Draft", user_id="u1")
        )
        updated = await store.update_task(
            created.task_id,
            title="Final",
            status="done",
            priority="high",
            tags=["release"],
        )
        assert updated is not None
        assert updated.title == "Final"
        assert updated.status is TaskStatus.DONE
        assert updated.priority is TaskPriority.HIGH
        assert updated.tags == ["release"]
        assert updated.updated_at > created.updated_at

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, store):
        await store.initialize()
        result = await store.update_task("nonexistent", title="Nope")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_task(self, store):
        created = await store.create_task(
            UserTask(task_id="", title="Remove me", user_id="u1")
        )
        assert await store.delete_task(created.task_id) is True
        assert await store.get_task(created.task_id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store):
        await store.initialize()
        assert await store.delete_task("nope") is False

    @pytest.mark.asyncio
    async def test_list_by_orchestration(self, store):
        await store.create_task(
            UserTask(
                task_id="",
                title="Linked",
                user_id="u1",
                linked_orchestration_id="orch-1",
            )
        )
        await store.create_task(
            UserTask(task_id="", title="Unlinked", user_id="u1")
        )

        linked = await store.list_by_orchestration("orch-1")
        assert len(linked) == 1
        assert linked[0].title == "Linked"

    @pytest.mark.asyncio
    async def test_pagination(self, store):
        for i in range(5):
            await store.create_task(
                UserTask(task_id="", title=f"Task {i}", user_id="u1")
            )
        page = await store.list_tasks(user_id="u1", limit=2, offset=0)
        assert len(page) == 2
        page2 = await store.list_tasks(user_id="u1", limit=2, offset=2)
        assert len(page2) == 2
        all_ids = {t.task_id for t in page} | {t.task_id for t in page2}
        assert len(all_ids) == 4  # No overlap


class TestTaskRouterValidation:
    """Test router helper functions."""

    def test_validate_status_valid(self):
        from magi.api.routers.tasks import _validate_status
        assert _validate_status("open") is TaskStatus.OPEN
        assert _validate_status("done") is TaskStatus.DONE

    def test_validate_status_invalid(self):
        from magi.api.routers.tasks import _validate_status
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _validate_status("invalid")
        assert exc_info.value.status_code == 400

    def test_validate_priority_valid(self):
        from magi.api.routers.tasks import _validate_priority
        assert _validate_priority("urgent") is TaskPriority.URGENT

    def test_validate_priority_invalid(self):
        from magi.api.routers.tasks import _validate_priority
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _validate_priority("extreme")
        assert exc_info.value.status_code == 400
