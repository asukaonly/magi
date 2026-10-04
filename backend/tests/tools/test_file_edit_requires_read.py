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
async def test_file_edit_requires_reading_the_current_bytes_in_the_same_session(tmp_path):
    target = tmp_path / "f.py"
    target.write_text("x = 1\n")
    ctx = _ctx(tmp_path)
    read, edit = FileReadTool(), FileEditTool()

    async def replace(old, new, context=ctx):
        return await edit.execute(
            {"path": str(target), "old_string": old, "new_string": new}, context
        )

    unread = await replace("x = 1", "x = 2")
    assert not unread.success and "read" in unread.error.lower()
    assert target.read_text() == "x = 1\n"
    assert (await read.execute({"path": str(target)}, ctx)).success
    other_session = await replace("x = 1", "x = 2", _ctx(tmp_path, session_id="s2"))
    assert not other_session.success and "read" in other_session.error.lower()
    assert target.read_text() == "x = 1\n"
    target.write_text("x = 99\n")
    stale = await replace("x = 99", "x = 2")
    assert not stale.success and "read" in stale.error.lower()
    assert target.read_text() == "x = 99\n"
    assert (await read.execute({"path": str(target)}, ctx)).success
    accepted = await replace("x = 99", "x = 2")
    assert accepted.success, accepted.error
    assert target.read_text() == "x = 2\n"


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
