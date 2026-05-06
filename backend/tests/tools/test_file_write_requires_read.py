"""file_write must refuse to overwrite existing files that have not been read."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.builtin.file_write_tool import FileWriteTool
from magi.tools.schema import ToolExecutionContext


def _ctx(workspace: Path, session_id: str | None = "s1") -> ToolExecutionContext:
    env_vars = {"session_id": session_id} if session_id else {}
    return ToolExecutionContext(agent_id="a", workspace=str(workspace), env_vars=env_vars)


@pytest.mark.asyncio
async def test_overwrite_existing_blocked_without_read(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("old content")
    write = FileWriteTool()
    res = await write.execute(
        {"path": str(target), "content": "new content"},
        _ctx(tmp_path),
    )
    assert not res.success
    assert "read" in (res.error or "").lower()
    assert target.read_text() == "old content"


@pytest.mark.asyncio
async def test_overwrite_existing_allowed_after_read(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("old content")
    ctx = _ctx(tmp_path)
    read = FileReadTool()
    write = FileWriteTool()
    await read.execute({"path": str(target)}, ctx)
    res = await write.execute(
        {"path": str(target), "content": "new content"},
        ctx,
    )
    assert res.success, res.error
    assert target.read_text() == "new content"


@pytest.mark.asyncio
async def test_create_new_file_allowed_without_read(tmp_path: Path) -> None:
    target = tmp_path / "brand_new.txt"
    write = FileWriteTool()
    res = await write.execute(
        {"path": str(target), "content": "fresh"},
        _ctx(tmp_path),
    )
    assert res.success, res.error
    assert target.read_text() == "fresh"


@pytest.mark.asyncio
async def test_append_to_existing_allowed_without_read(tmp_path: Path) -> None:
    target = tmp_path / "log.txt"
    target.write_text("line1\n")
    write = FileWriteTool()
    res = await write.execute(
        {"path": str(target), "content": "line2\n", "mode": "append"},
        _ctx(tmp_path),
    )
    assert res.success, res.error
    assert target.read_text() == "line1\nline2\n"


@pytest.mark.asyncio
async def test_overwrite_allowed_when_no_session_id(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("old")
    write = FileWriteTool()
    res = await write.execute(
        {"path": str(target), "content": "new"},
        _ctx(tmp_path, session_id=None),
    )
    assert res.success, res.error
    assert target.read_text() == "new"
