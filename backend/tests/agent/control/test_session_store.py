"""Unit tests for the control-plane session store."""

from __future__ import annotations

import asyncio

import pytest

from magi.control.session_store import (
    ControlSessionClearedError,
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
    assert [t.content for t in listed] == ["read spec", "write tests", "ship"]
    assert all(t.created_at_ms > 0 for t in listed)
    assert all(t.updated_at_ms >= t.created_at_ms for t in listed)


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
    contents = [t.content for t in store.list_todos("s1")]
    assert contents == ["new1", "new2"]


@pytest.mark.asyncio
async def test_todo_accepts_content_payloads() -> None:
    store = ControlSessionStore()
    todos = await store.replace_todos(
        "s1",
        [
            {
                "id": "todo-1",
                "content": "inspect logs",
                "status": "in_progress",
                "created_at_ms": 10,
                "updated_at_ms": 25,
            }
        ],
    )

    assert [t.content for t in todos] == ["inspect logs"]
    assert todos[0].created_at_ms == 10
    assert todos[0].updated_at_ms == 25


@pytest.mark.asyncio
async def test_ask_open_then_close_user() -> None:
    store = ControlSessionStore()
    ask = await store.open_ask(
        "s1",
        question="Continue?",
        options=["yes", "no"],
        allow_free_text=False,
        timeout_seconds=30,
    )
    assert ask.resolution is None
    assert ask.options == ("yes", "no")
    assert store.ask_state("s1") is ask
    payload = ask.to_dict()
    assert payload["status"] == "pending"
    assert payload["created_at_ms"] == int(ask.asked_at * 1000)
    assert payload["timeout_seconds"] == 30.0
    assert payload["expires_at_ms"] == int(ask.expires_at * 1000)

    closed = await store.close_ask(
        "s1",
        request_id=ask.request_id,
        expected_generation=ask.clear_generation,
        answer="yes",
        resolution="user",
    )
    assert closed is not None
    assert closed.answer == "yes"
    assert closed.resolution == "user"
    assert closed.answered_at is not None
    assert closed.to_dict()["status"] == "answered"


@pytest.mark.asyncio
async def test_ask_close_without_open_returns_none() -> None:
    store = ControlSessionStore()
    assert (
        await store.close_ask(
            "s1",
            request_id="missing",
            expected_generation=0,
            answer=None,
            resolution="timeout",
        )
        is None
    )


@pytest.mark.asyncio
async def test_reset_single_session() -> None:
    store = ControlSessionStore()
    await store.enter_plan_mode("s1")
    await store.enter_plan_mode("s2")
    store.reset("s1")
    assert store.plan_state("s1").active is False
    assert store.plan_state("s2").active is True


@pytest.mark.asyncio
async def test_full_clear_erases_session_content_and_reopens_cleanly() -> None:
    store = ControlSessionStore()
    await store.enter_plan_mode("s1")
    await store.replace_todos("s1", [{"title": "secret todo"}])
    old_ask = await store.open_ask(
        "s1",
        question="secret question",
        request_id="old-ask",
    )

    async with store.user_content_clear_boundary():
        assert store.plan_state("s1").active is False
        assert store.plan_allows("s1", "bash") is False
        assert store.list_todos("s1") == []
        assert store.ask_state("s1") is None
        with pytest.raises(ControlSessionClearedError):
            await store.enter_plan_mode("during-clear")

    assert store.plan_state("s1").active is False
    assert store.list_todos("s1") == []
    assert store.ask_state("s1") is None
    with pytest.raises(ControlSessionClearedError):
        await store.close_ask(
            "s1",
            request_id=old_ask.request_id,
            expected_generation=old_ask.clear_generation,
            answer="late answer",
            resolution="user",
        )

    await store.enter_plan_mode("fresh")
    await store.replace_todos("fresh", [{"title": "new todo"}])
    fresh_ask = await store.open_ask(
        "fresh",
        question="new question",
        request_id="fresh-ask",
    )
    assert store.plan_state("fresh").active is True
    assert [item.content for item in store.list_todos("fresh")] == ["new todo"]
    assert store.ask_state("fresh") is fresh_ask


@pytest.mark.asyncio
async def test_full_clear_waits_for_admitted_operations_and_rejects_queued_writes() -> None:
    store = ControlSessionStore()
    clear_entered = asyncio.Event()
    release_clear = asyncio.Event()

    async def clear() -> None:
        async with store.user_content_clear_boundary():
            clear_entered.set()
            await release_clear.wait()

    async with store.user_content_operation():
        clear_task = asyncio.create_task(clear())
        await asyncio.sleep(0)
        assert clear_entered.is_set() is False
        with pytest.raises(ControlSessionClearedError):
            await store.replace_todos("old", [{"title": "late todo"}])

    await asyncio.wait_for(clear_entered.wait(), timeout=1)
    assert store.list_todos("old") == []
    release_clear.set()
    await clear_task
