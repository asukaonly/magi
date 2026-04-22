"""Unit tests for the control-plane session store."""

from __future__ import annotations

import pytest

from magi.agent.control.session_store import (
    ControlSessionStore,
    DEFAULT_PLAN_MODE_ALLOWED_TOOLS,
    TodoItem,
    TodoListError,
    TodoStatus,
)


@pytest.mark.asyncio
async def test_plan_mode_toggle_and_allowlist() -> None:
    store = ControlSessionStore()
    sid = "s1"

    # Default: no plan mode → everything allowed.
    assert store.plan_allows(sid, "bash") is True

    state = await store.enter_plan_mode(sid)
    assert state.active is True
    assert state.entered_at is not None
    # Default allowlist permits read-only tools but denies writers.
    assert store.plan_allows(sid, "file_read") is True
    assert store.plan_allows(sid, "bash") is False
    assert store.plan_allows(sid, "file_write") is False
    # Plan-mode tools themselves stay callable.
    assert store.plan_allows(sid, "enter_plan_mode") is True
    assert store.plan_allows(sid, "exit_plan_mode") is True
    assert store.plan_allows(sid, "ask_user_question") is True
    assert store.plan_allows(sid, "todo_write") is True

    state = await store.exit_plan_mode(sid, plan_text="do X then Y")
    assert state.active is False
    assert state.plan_text == "do X then Y"
    assert store.plan_allows(sid, "bash") is True


@pytest.mark.asyncio
async def test_plan_mode_allowlist_is_isolated_per_session() -> None:
    store = ControlSessionStore()
    await store.enter_plan_mode("s1")
    assert store.plan_allows("s1", "bash") is False
    # A different session is unaffected.
    assert store.plan_allows("s2", "bash") is True


@pytest.mark.asyncio
async def test_plan_mode_custom_allowlist() -> None:
    store = ControlSessionStore()
    await store.enter_plan_mode("s1", allowed_tools=["only_this"])
    assert store.plan_allows("s1", "only_this") is True
    assert store.plan_allows("s1", "file_read") is False


def test_default_allowlist_is_stable() -> None:
    # Mild guard against accidental removal.
    assert "file_read" in DEFAULT_PLAN_MODE_ALLOWED_TOOLS
    assert "memory_query" in DEFAULT_PLAN_MODE_ALLOWED_TOOLS
    assert "enter_plan_mode" in DEFAULT_PLAN_MODE_ALLOWED_TOOLS
    assert "exit_plan_mode" in DEFAULT_PLAN_MODE_ALLOWED_TOOLS


@pytest.mark.asyncio
async def test_todo_replace_happy_path() -> None:
    store = ControlSessionStore()
    todos = await store.replace_todos(
        "s1",
        [
            {"title": "read spec"},
            {"title": "write tests", "status": "in_progress"},
            {"title": "ship", "status": "not_started"},
        ],
    )
    assert len(todos) == 3
    assert all(isinstance(t, TodoItem) for t in todos)
    assert todos[1].status is TodoStatus.IN_PROGRESS
    # ids auto-generated when omitted.
    assert all(t.id for t in todos)

    listed = store.list_todos("s1")
    assert [t.title for t in listed] == ["read spec", "write tests", "ship"]


@pytest.mark.asyncio
async def test_todo_rejects_two_in_progress() -> None:
    store = ControlSessionStore()
    with pytest.raises(TodoListError):
        await store.replace_todos(
            "s1",
            [
                {"title": "a", "status": "in_progress"},
                {"title": "b", "status": "in_progress"},
            ],
        )
    # State must remain empty on failure.
    assert store.list_todos("s1") == []


@pytest.mark.asyncio
async def test_todo_rejects_duplicate_ids() -> None:
    store = ControlSessionStore()
    with pytest.raises(TodoListError):
        await store.replace_todos(
            "s1",
            [
                {"id": "x", "title": "one"},
                {"id": "x", "title": "two"},
            ],
        )


@pytest.mark.asyncio
async def test_todo_rejects_empty_title() -> None:
    store = ControlSessionStore()
    with pytest.raises(TodoListError):
        await store.replace_todos("s1", [{"title": "   "}])


@pytest.mark.asyncio
async def test_todo_full_replace_semantics() -> None:
    store = ControlSessionStore()
    await store.replace_todos("s1", [{"title": "old"}])
    await store.replace_todos(
        "s1",
        [{"title": "new1"}, {"title": "new2"}],
    )
    titles = [t.title for t in store.list_todos("s1")]
    assert titles == ["new1", "new2"]


@pytest.mark.asyncio
async def test_ask_open_then_close_user() -> None:
    store = ControlSessionStore()
    ask = await store.open_ask(
        "s1",
        question="Continue?",
        options=["yes", "no"],
        allow_free_text=False,
    )
    assert ask.resolution is None
    assert ask.options == ("yes", "no")
    assert store.ask_state("s1") is ask

    closed = await store.close_ask("s1", answer="yes", resolution="user")
    assert closed is not None
    assert closed.answer == "yes"
    assert closed.resolution == "user"
    assert closed.answered_at is not None


@pytest.mark.asyncio
async def test_ask_close_without_open_returns_none() -> None:
    store = ControlSessionStore()
    assert await store.close_ask("s1", answer=None, resolution="timeout") is None


@pytest.mark.asyncio
async def test_reset_single_session() -> None:
    store = ControlSessionStore()
    await store.enter_plan_mode("s1")
    await store.enter_plan_mode("s2")
    store.reset("s1")
    assert store.plan_state("s1").active is False
    assert store.plan_state("s2").active is True
