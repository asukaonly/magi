"""Exercise registered task queries against the real durable task store."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.agent.background import BackgroundTask, BackgroundTaskSpec, BackgroundTaskStatus, BackgroundTaskStore
from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities
from magi.tools.builtin.task_query_tool import TaskQueryTool
from magi.tools.core_tools import CORE_TOOL_CLASSES
from magi.tools.schema import ToolExecutionContext
from magi.tools.system_tools import resolve_resident_system_tools


@pytest.fixture
def task_context(runtime_paths_with_schema, monkeypatch):
    store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    monkeypatch.setattr(
        "magi.agent.background.provider.resolve_background_task_manager",
        lambda: SimpleNamespace(store=store),
    )
    reset_tool_capabilities()
    context = ToolExecutionContext(
        agent_id="chat", env_vars={"user_id": "alice", "session_id": "session-a"},
        capabilities=build_tool_capabilities(),
    )
    yield store, context
    reset_tool_capabilities()


async def _task(store, *, user="alice", session="session-a", status=BackgroundTaskStatus.PENDING):
    task = BackgroundTask.new(BackgroundTaskSpec(
        user_id=user, session_id=session, origin_turn_id="turn-a", title="Research",
        goal="Prepare a report", system_prompt="PRIVATE SYSTEM PROMPT",
        working_context="PRIVATE RUNTIME CONTEXT",
    ))
    task.status = status
    task.result_payload = {"private": "RAW RUNTIME PAYLOAD"}
    await store.create_task(task)
    return task


@pytest.mark.asyncio
async def test_queries_are_scoped_and_do_not_expose_run_internals(task_context):
    store, context = task_context
    own = await _task(store)
    other_session = await _task(store, session="session-b")
    other_user = await _task(store, user="bob")
    tool = TaskQueryTool()
    result = await tool.execute({}, context)
    assert result.success
    assert [task["task_id"] for task in result.data["tasks"]] == [own.task_id]
    assert "PRIVATE" not in str(result.data)
    assert "RAW RUNTIME" not in str(result.data)

    across = await tool.execute({"scope": "user"}, context)
    assert {task["task_id"] for task in across.data["tasks"]} == {own.task_id, other_session.task_id}
    for task_id, scope in [(other_user.task_id, "user"), (other_session.task_id, "session"), ("missing", "user")]:
        denied = await tool.execute({"task_id": task_id, "scope": scope}, context)
        assert not denied.success
        assert denied.error_code == "TASK_NOT_FOUND"


@pytest.mark.asyncio
async def test_status_pagination_and_live_updates(task_context):
    store, context = task_context
    await _task(store, status=BackgroundTaskStatus.SUCCEEDED)
    for _ in range(3):
        await _task(store, status=BackgroundTaskStatus.RUNNING)
    tool = TaskQueryTool()
    first = await tool.execute({"status": "running", "limit": 2}, context)
    assert len(first.data["tasks"]) == 2
    assert first.data["has_more"]
    second = await tool.execute({"status": "running", "limit": 2, "offset": first.data["next_offset"]}, context)
    assert len(second.data["tasks"]) == 1
    assert not second.data["has_more"]
    task_id = first.data["tasks"][0]["task_id"]
    task = await store.get_task(task_id)
    task.status = BackgroundTaskStatus.SUSPENDED_WAITING_USER
    task.summary = "x" * 3000
    await store.update_task(task)
    updated = await tool.execute({"task_id": task_id}, context)
    snapshot = updated.data["tasks"][0]
    assert snapshot["requires_user_input"]
    assert snapshot["status"] == "suspended_waiting_user"
    assert len(snapshot["summary"]) == 2000
    assert snapshot["truncated_fields"] == ["summary"]
    assert "progress" not in snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{"user_id": "bob"}, {"limit": 21}, {"offset": -1}, {"status": "complete"}, {"limit": True}])
async def test_invalid_queries_are_rejected(task_context, params):
    _, context = task_context
    result = await TaskQueryTool().execute(params, context)
    assert not result.success
    assert result.error_code == "INVALID_PARAMETERS"


@pytest.mark.asyncio
async def test_missing_identity_never_lists_all_users(task_context):
    _, context = task_context
    context.env_vars.clear()
    result = await TaskQueryTool().execute({"scope": "user"}, context)
    assert not result.success
    assert result.error_code == "TASK_SCOPE_UNAVAILABLE"


def test_task_query_is_registered_but_not_unconditionally_resident():
    assert TaskQueryTool in CORE_TOOL_CLASSES
    registry = SimpleNamespace(list_tools=lambda category=None: [] if category else ["task_query"])
    assert "task_query" not in resolve_resident_system_tools(registry)
