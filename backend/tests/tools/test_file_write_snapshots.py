"""file_write overwrite must snapshot; new-file and append must not."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi_plugin_sdk.workspace_cache import SnapshotRef, resolve_session_cache
from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.builtin.file_write_tool import FileWriteTool
from magi.tools.schema import ToolExecutionContext


def _ctx(workspace: Path, session_id: str | None = "s1") -> ToolExecutionContext:
    env_vars = {"session_id": session_id} if session_id else {}
    return ToolExecutionContext(agent_id="a", workspace=str(workspace), env_vars=env_vars)


@pytest.mark.asyncio
async def test_overwrite_records_write_op_with_prior_snapshot(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_bytes(b"old")
    ctx = _ctx(tmp_path)
    await FileReadTool().execute({"path": str(target)}, ctx)
    res = await FileWriteTool().execute(
        {"path": str(target), "content": "new"},
        ctx,
    )
    assert res.success, res.error
    sc = resolve_session_cache(tmp_path, "s1")
    edits = list(sc.iter_edits())
    assert len(edits) == 1
    rec = edits[0]
    assert rec.op == "write"
    assert rec.path == "f.txt"
    assert sc.read_snapshot(SnapshotRef(sha256=rec.snapshot_ref)) == b"old"


@pytest.mark.asyncio
async def test_create_new_file_does_not_record(tmp_path: Path) -> None:
    target = tmp_path / "fresh.txt"
    ctx = _ctx(tmp_path)
    res = await FileWriteTool().execute(
        {"path": str(target), "content": "hi"},
        ctx,
    )
    assert res.success, res.error
    sc = resolve_session_cache(tmp_path, "s1")
    assert list(sc.iter_edits()) == []


@pytest.mark.asyncio
async def test_append_does_not_record(tmp_path: Path) -> None:
    target = tmp_path / "log.txt"
    target.write_text("a\n")
    ctx = _ctx(tmp_path)
    res = await FileWriteTool().execute(
        {"path": str(target), "content": "b\n", "mode": "append"},
        ctx,
    )
    assert res.success, res.error
    sc = resolve_session_cache(tmp_path, "s1")
    assert list(sc.iter_edits()) == []
