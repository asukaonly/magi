"""file_read must record successful reads into the session cache."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi_plugin_sdk.workspace_cache import resolve_session_cache
from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.schema import ToolExecutionContext


def _ctx(workspace: Path, session_id: str | None = "s1") -> ToolExecutionContext:
    env_vars = {"session_id": session_id} if session_id else {}
    return ToolExecutionContext(agent_id="a", workspace=str(workspace), env_vars=env_vars)


@pytest.mark.asyncio
async def test_file_read_records_into_session_cache(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("hi\n")
    tool = FileReadTool()
    res = await tool.execute({"path": str(target)}, _ctx(tmp_path))
    assert res.success
    sc = resolve_session_cache(tmp_path, "s1")
    paths = [r.path for r in sc.iter_reads()]
    assert "hello.txt" in paths


@pytest.mark.asyncio
async def test_file_read_no_session_id_does_not_record(tmp_path: Path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("hi\n")
    tool = FileReadTool()
    res = await tool.execute({"path": str(target)}, _ctx(tmp_path, session_id=None))
    assert res.success
    cache_dir = tmp_path / ".magi"
    if cache_dir.exists():
        sessions = cache_dir / "sessions"
        assert not sessions.exists() or not list(sessions.iterdir())


@pytest.mark.asyncio
async def test_file_read_failure_does_not_record(tmp_path: Path) -> None:
    tool = FileReadTool()
    res = await tool.execute({"path": str(tmp_path / "nope.txt")}, _ctx(tmp_path))
    assert not res.success
    cache_dir = tmp_path / ".magi" / "sessions" / "s1"
    if cache_dir.exists():
        reads = cache_dir / "reads.jsonl"
        assert not reads.exists() or reads.read_text() == ""
