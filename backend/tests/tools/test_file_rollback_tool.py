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
async def test_rollback_records_reversible_history_without_touching_other_paths(tmp_path):
    a, b, context = await _make_two_edits(tmp_path)
    cache = resolve_session_cache(tmp_path, "s1")
    before = list(cache.iter_edits())
    assert len(before) == 2
    for expected_content, count in [("a1\n", 3), ("a2\n", 4)]:
        result = await FileRollbackTool().execute({"mode": "path", "path": str(a)}, context)
        assert result.success, result.error
        assert a.read_text() == expected_content
        assert b.read_text() == "b2\n"
        history = list(cache.iter_edits())
        assert len(history) == count
        assert history[:2] == before
        assert history[-1].path == "a.py"


@pytest.mark.asyncio
async def test_rollback_requires_session_id(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x")
    res = await FileRollbackTool().execute(
        {"mode": "last"}, _ctx(tmp_path, session_id=None)
    )
    assert not res.success
    assert "session" in (res.error or "").lower()


@pytest.mark.parametrize(
    "expected_error_field,mode_value",
    [
        pytest.param("mode", "wat", id="rollback_rejects_unknown_mode"),
        pytest.param("path", "path", id="rollback_path_mode_requires_path"),
    ],
)
@pytest.mark.asyncio
async def test_rollback_rejects_invalid_mode_or_missing_path(
    tmp_path: Path, expected_error_field, mode_value
) -> None:
    res = await FileRollbackTool().execute({"mode": mode_value}, _ctx(tmp_path))
    assert not res.success
    assert expected_error_field in (res.error or "").lower()

@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["last","all","path"])
async def test_rollback_without_history_preserves_file_and_empty_journal(tmp_path, mode):
    from magi_plugin_sdk.workspace_cache import resolve_session_cache
    untouched = tmp_path / "untouched.txt"
    untouched.write_bytes(b"untouched bytes")
    params = {"mode":mode}
    if mode == "path":
        params["path"] = str(untouched)
    result = await FileRollbackTool().execute(params, _ctx(tmp_path))
    assert result.success, result.error
    assert result.data["restored"] == []
    assert untouched.read_bytes() == b"untouched bytes"
    assert list(resolve_session_cache(tmp_path,"s1").iter_edits()) == []
