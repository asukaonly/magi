"""file_edit must refuse to modify files that have not been read in-session."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.builtin.file_edit_tool import FileEditTool
from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.schema import ToolExecutionContext


def _ctx(workspace: Path, session_id: str | None = "s1") -> ToolExecutionContext:
    env_vars = {"session_id": session_id} if session_id else {}
    return ToolExecutionContext(agent_id="a", workspace=str(workspace), env_vars=env_vars)


@pytest.mark.asyncio
async def test_file_edit_blocked_without_prior_read(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("x = 1\n")
    edit = FileEditTool()
    res = await edit.execute(
        {"path": str(target), "old_string": "x = 1", "new_string": "x = 2"},
        _ctx(tmp_path),
    )
    assert not res.success
    assert "read" in (res.error or "").lower()
    assert target.read_text() == "x = 1\n"


@pytest.mark.asyncio
async def test_file_edit_allowed_after_read(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("x = 1\n")
    ctx = _ctx(tmp_path)
    read = FileReadTool()
    edit = FileEditTool()
    assert (await read.execute({"path": str(target)}, ctx)).success
    res = await edit.execute(
        {"path": str(target), "old_string": "x = 1", "new_string": "x = 2"},
        ctx,
    )
    assert res.success, res.error
    assert target.read_text() == "x = 2\n"


@pytest.mark.asyncio
async def test_file_edit_blocked_after_external_change(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("x = 1\n")
    ctx = _ctx(tmp_path)
    read = FileReadTool()
    edit = FileEditTool()
    await read.execute({"path": str(target)}, ctx)
    target.write_text("x = 99  # changed by someone else\n")
    res = await edit.execute(
        {"path": str(target), "old_string": "x = 99", "new_string": "x = 2"},
        ctx,
    )
    assert not res.success
    assert "read" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_file_edit_allowed_when_no_session_id(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("x = 1\n")
    edit = FileEditTool()
    res = await edit.execute(
        {"path": str(target), "old_string": "x = 1", "new_string": "x = 2"},
        _ctx(tmp_path, session_id=None),
    )
    assert res.success, res.error
    assert target.read_text() == "x = 2\n"
