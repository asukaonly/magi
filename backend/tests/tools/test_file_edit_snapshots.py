"""file_edit must snapshot prior bytes and append an EditRecord."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi_plugin_sdk.workspace_cache import SnapshotRef, resolve_session_cache
from magi.tools.builtin.file_edit_tool import FileEditTool
from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.schema import ToolExecutionContext


def _ctx(workspace: Path, session_id: str | None = "s1") -> ToolExecutionContext:
    env_vars = {"session_id": session_id} if session_id else {}
    return ToolExecutionContext(agent_id="a", workspace=str(workspace), env_vars=env_vars)


@pytest.mark.asyncio
async def test_file_edit_records_replace_op_and_snapshot(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("x = 1\n")
    ctx = _ctx(tmp_path)
    await FileReadTool().execute({"path": str(target)}, ctx)
    res = await FileEditTool().execute(
        {"path": str(target), "old_string": "x = 1", "new_string": "x = 2"},
        ctx,
    )
    assert res.success, res.error
    sc = resolve_session_cache(tmp_path, "s1")
    edits = list(sc.iter_edits())
    assert len(edits) == 1
    rec = edits[0]
    assert rec.op == "replace"
    assert rec.path == "f.py"
    snapshot_bytes = sc.read_snapshot(SnapshotRef(sha256=rec.snapshot_ref))
    assert snapshot_bytes == b"x = 1\n"


@pytest.mark.asyncio
async def test_file_edit_no_session_id_does_not_record(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("x = 1\n")
    ctx = _ctx(tmp_path, session_id=None)
    res = await FileEditTool().execute(
        {"path": str(target), "old_string": "x = 1", "new_string": "x = 2"},
        ctx,
    )
    assert res.success, res.error
    cache_dir = tmp_path / ".magi" / "sessions"
    if cache_dir.exists():
        assert not list(cache_dir.iterdir())


@pytest.mark.asyncio
async def test_file_edit_failure_path_no_record(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("x = 1\n")
    ctx = _ctx(tmp_path)
    await FileReadTool().execute({"path": str(target)}, ctx)
    res = await FileEditTool().execute(
        {"path": str(target), "old_string": "DOES_NOT_MATCH", "new_string": "y"},
        ctx,
    )
    assert not res.success
    sc = resolve_session_cache(tmp_path, "s1")
    assert list(sc.iter_edits()) == []
