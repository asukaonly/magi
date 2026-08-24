"""Integration tests for the file_rollback tool."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi_plugin_sdk.workspace_cache import resolve_session_cache
from magi.tools.builtin.file_edit_tool import FileEditTool
from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.builtin.file_rollback_tool import FileRollbackTool
from magi.tools.schema import ToolExecutionContext


def _ctx(workspace: Path, session_id: str | None = "s1") -> ToolExecutionContext:
    env_vars = {"session_id": session_id} if session_id else {}
    return ToolExecutionContext(agent_id="a", workspace=str(workspace), env_vars=env_vars)


async def _make_two_edits(workspace: Path) -> tuple[Path, Path, ToolExecutionContext]:
    a = workspace / "a.py"
    b = workspace / "b.py"
    a.write_text("a1\n")
    b.write_text("b1\n")
    ctx = _ctx(workspace)
    await FileReadTool().execute({"path": str(a)}, ctx)
    await FileEditTool().execute(
        {"path": str(a), "old_string": "a1", "new_string": "a2"}, ctx
    )
    await FileReadTool().execute({"path": str(b)}, ctx)
    await FileEditTool().execute(
        {"path": str(b), "old_string": "b1", "new_string": "b2"}, ctx
    )
    return a, b, ctx


@pytest.mark.asyncio
async def test_rollback_last_undoes_most_recent_edit(tmp_path: Path) -> None:
    a, b, ctx = await _make_two_edits(tmp_path)
    res = await FileRollbackTool().execute({"mode": "last"}, ctx)
    assert res.success, res.error
    assert b.read_text() == "b1\n"
    assert a.read_text() == "a2\n"
    assert res.data["restored"]
    assert res.data["restored"][0]["path"] == "b.py"


@pytest.mark.asyncio
async def test_rollback_all_undoes_in_reverse(tmp_path: Path) -> None:
    a, b, ctx = await _make_two_edits(tmp_path)
    res = await FileRollbackTool().execute({"mode": "all"}, ctx)
    assert res.success, res.error
    assert a.read_text() == "a1\n"
    assert b.read_text() == "b1\n"
    paths_in_order = [r["path"] for r in res.data["restored"]]
    assert paths_in_order == ["b.py", "a.py"]


@pytest.mark.asyncio
async def test_rollback_path_undoes_only_that_path(tmp_path: Path) -> None:
    a, b, ctx = await _make_two_edits(tmp_path)
    res = await FileRollbackTool().execute(
        {"mode": "path", "path": str(a)}, ctx
    )
    assert res.success, res.error
    assert a.read_text() == "a1\n"
    assert b.read_text() == "b2\n", "b must be untouched"


@pytest.mark.asyncio
async def test_rollback_path_with_no_history_succeeds_empty(tmp_path: Path) -> None:
    other = tmp_path / "untouched.txt"
    other.write_text("hi")
    ctx = _ctx(tmp_path)
    res = await FileRollbackTool().execute(
        {"mode": "path", "path": str(other)}, ctx
    )
    assert res.success, res.error
    assert res.data["restored"] == []


@pytest.mark.asyncio
async def test_rollback_empty_session_is_success_empty(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    res = await FileRollbackTool().execute({"mode": "last"}, ctx)
    assert res.success, res.error
    assert res.data["restored"] == []


@pytest.mark.asyncio
async def test_rollback_dry_run_makes_no_disk_changes(tmp_path: Path) -> None:
    a, b, ctx = await _make_two_edits(tmp_path)
    before_a = a.read_text()
    before_b = b.read_text()
    res = await FileRollbackTool().execute({"mode": "all", "dry_run": True}, ctx)
    assert res.success, res.error
    assert a.read_text() == before_a
    assert b.read_text() == before_b
    assert len(res.data["restored"]) == 2
    sc = resolve_session_cache(tmp_path, "s1")
    assert len(list(sc.iter_edits())) == 2


@pytest.mark.asyncio
async def test_rollback_records_new_edit_so_it_is_undoable(tmp_path: Path) -> None:
    a, _b, ctx = await _make_two_edits(tmp_path)
    sc = resolve_session_cache(tmp_path, "s1")
    pre_count = len(list(sc.iter_edits()))
    await FileRollbackTool().execute({"mode": "path", "path": str(a)}, ctx)
    post_count = len(list(sc.iter_edits()))
    assert post_count == pre_count + 1


@pytest.mark.asyncio
async def test_rollback_after_rollback_returns_to_post_first_edit_state(tmp_path: Path) -> None:
    a, _b, ctx = await _make_two_edits(tmp_path)
    await FileRollbackTool().execute({"mode": "path", "path": str(a)}, ctx)
    assert a.read_text() == "a1\n"
    await FileRollbackTool().execute({"mode": "path", "path": str(a)}, ctx)
    assert a.read_text() == "a2\n"


@pytest.mark.asyncio
async def test_rollback_requires_session_id(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x")
    res = await FileRollbackTool().execute(
        {"mode": "last"}, _ctx(tmp_path, session_id=None)
    )
    assert not res.success
    assert "session" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_rollback_rejects_unknown_mode(tmp_path: Path) -> None:
    res = await FileRollbackTool().execute({"mode": "wat"}, _ctx(tmp_path))
    assert not res.success
    assert "mode" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_rollback_path_mode_requires_path(tmp_path: Path) -> None:
    res = await FileRollbackTool().execute({"mode": "path"}, _ctx(tmp_path))
    assert not res.success
    assert "path" in (res.error or "").lower()


def test_file_rollback_is_listed_in_builtin_exports() -> None:
    from magi.tools.builtin import FileRollbackTool as FromBuiltin
    from magi.tools import FileRollbackTool as FromTools
    from magi.tools.core_tools import CORE_TOOL_CLASSES
    assert FromBuiltin is FileRollbackTool
    assert FromTools is FileRollbackTool
    assert FileRollbackTool in CORE_TOOL_CLASSES
