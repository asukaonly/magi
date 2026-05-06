"""Tests for SessionCache todo state."""
from __future__ import annotations

from pathlib import Path

from magi.agent.workspace_cache.contracts import TodoItem, TodoState
from magi.agent.workspace_cache.root import WorkspaceCacheRoot
from magi.agent.workspace_cache.session import SessionCache


def _sc(tmp_path: Path) -> SessionCache:
    return SessionCache(root=WorkspaceCacheRoot.ensure(tmp_path), session_id="s1")


def test_read_todo_returns_empty_state_when_missing(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    state = sc.read_todo()
    assert state.items == []
    assert state.updated_at_ms == 0


def test_write_todo_persists_and_round_trips(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    state = TodoState(
        items=[TodoItem(id="1", text="do thing", done=False)],
        updated_at_ms=1_700_000_000_000,
    )
    sc.write_todo(state)
    loaded = sc.read_todo()
    assert loaded == state


def test_write_todo_replaces_previous(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    sc.write_todo(TodoState(items=[TodoItem(id="1", text="a")], updated_at_ms=1))
    sc.write_todo(TodoState(items=[TodoItem(id="2", text="b")], updated_at_ms=2))
    state = sc.read_todo()
    assert [i.id for i in state.items] == ["2"]
    assert state.updated_at_ms == 2


def test_write_todo_atomic_no_partial_state(tmp_path: Path) -> None:
    sc = _sc(tmp_path)
    sc.write_todo(TodoState(items=[TodoItem(id="x", text="x")], updated_at_ms=1))
    todo_path = tmp_path / ".magi" / "sessions" / "s1" / "todo.json"
    assert todo_path.exists()
    leftovers = [p for p in todo_path.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []
