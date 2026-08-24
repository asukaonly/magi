"""Integration tests for the file_diff tool."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.builtin.file_diff_tool import FileDiffTool
from magi.tools.builtin.file_edit_tool import FileEditTool
from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.builtin.file_write_tool import FileWriteTool
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
    await FileEditTool().execute({"path": str(a), "old_string": "a1", "new_string": "a2"}, ctx)
    await FileReadTool().execute({"path": str(b)}, ctx)
    await FileEditTool().execute({"path": str(b), "old_string": "b1", "new_string": "b2"}, ctx)
    return a, b, ctx


@pytest.mark.asyncio
async def test_diff_last_returns_unified_diff(tmp_path: Path) -> None:
    a, b, ctx = await _make_two_edits(tmp_path)
    res = await FileDiffTool().execute({"mode": "last"}, ctx)
    assert res.success, res.error
    assert len(res.data["diffs"]) == 1
    entry = res.data["diffs"][0]
    assert entry["path"] == "b.py"
    assert "-b1" in entry["diff_text"]
    assert "+b2" in entry["diff_text"]
    assert entry["binary"] is False


@pytest.mark.asyncio
async def test_diff_all_returns_reverse_chronological(tmp_path: Path) -> None:
    a, b, ctx = await _make_two_edits(tmp_path)
    res = await FileDiffTool().execute({"mode": "all"}, ctx)
    assert res.success, res.error
    paths = [d["path"] for d in res.data["diffs"]]
    assert paths == ["b.py", "a.py"]


@pytest.mark.asyncio
async def test_diff_path_returns_only_that_path(tmp_path: Path) -> None:
    a, b, ctx = await _make_two_edits(tmp_path)
    res = await FileDiffTool().execute({"mode": "path", "path": str(a)}, ctx)
    assert res.success, res.error
    assert len(res.data["diffs"]) == 1
    assert res.data["diffs"][0]["path"] == "a.py"


@pytest.mark.asyncio
async def test_diff_path_no_history_empty(tmp_path: Path) -> None:
    other = tmp_path / "untouched.txt"
    other.write_text("hi")
    res = await FileDiffTool().execute(
        {"mode": "path", "path": str(other)}, _ctx(tmp_path)
    )
    assert res.success, res.error
    assert res.data["diffs"] == []


@pytest.mark.asyncio
async def test_diff_empty_session_empty(tmp_path: Path) -> None:
    res = await FileDiffTool().execute({"mode": "last"}, _ctx(tmp_path))
    assert res.success, res.error
    assert res.data["diffs"] == []


@pytest.mark.asyncio
async def test_diff_reflects_current_disk_not_recorded_after(tmp_path: Path) -> None:
    a, _b, ctx = await _make_two_edits(tmp_path)
    a.write_text("a3 changed externally\n")
    res = await FileDiffTool().execute({"mode": "path", "path": str(a)}, ctx)
    assert res.success, res.error
    entry = res.data["diffs"][0]
    assert "+a3 changed externally" in entry["diff_text"]
    assert entry["current_sha256"] != entry["recorded_sha256_after"]


@pytest.mark.asyncio
async def test_diff_handles_deleted_after_edit(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    a.write_text("orig\n")
    ctx = _ctx(tmp_path)
    await FileReadTool().execute({"path": str(a)}, ctx)
    await FileEditTool().execute({"path": str(a), "old_string": "orig", "new_string": "edited"}, ctx)
    a.unlink()
    res = await FileDiffTool().execute({"mode": "last"}, ctx)
    assert res.success, res.error
    entry = res.data["diffs"][0]
    assert "-orig" in entry["diff_text"]


@pytest.mark.asyncio
async def test_diff_binary_content_marked(tmp_path: Path) -> None:
    from magi_plugin_sdk.workspace_cache import resolve_session_cache

    target = tmp_path / "blob.bin"
    target.write_bytes(b"\x00\x01before\xff")
    ctx = _ctx(tmp_path)
    # file_read is utf-8 only and can't read binary; record the read directly
    # so the read-before-edit constraint is satisfied.
    resolve_session_cache(tmp_path, "s1").record_read(target)
    await FileWriteTool().execute(
        {"path": str(target), "content": "\x00\x01after\xff"}, ctx
    )
    res = await FileDiffTool().execute({"mode": "last"}, ctx)
    assert res.success, res.error
    entry = res.data["diffs"][0]
    assert entry["binary"] is True
    assert "[binary diff suppressed]" in entry["diff_text"]


@pytest.mark.asyncio
async def test_diff_requires_session_id(tmp_path: Path) -> None:
    res = await FileDiffTool().execute(
        {"mode": "last"}, _ctx(tmp_path, session_id=None)
    )
    assert not res.success
    assert "session" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_diff_rejects_unknown_mode(tmp_path: Path) -> None:
    res = await FileDiffTool().execute({"mode": "wat"}, _ctx(tmp_path))
    assert not res.success
    assert "mode" in (res.error or "").lower()


@pytest.mark.asyncio
async def test_diff_path_mode_requires_path(tmp_path: Path) -> None:
    res = await FileDiffTool().execute({"mode": "path"}, _ctx(tmp_path))
    assert not res.success
    assert "path" in (res.error or "").lower()


def test_file_diff_is_listed_in_builtin_exports() -> None:
    from magi.tools.builtin import FileDiffTool as FromBuiltin
    from magi.tools import FileDiffTool as FromTools
    from magi.tools.core_tools import CORE_TOOL_CLASSES
    assert FromBuiltin is FileDiffTool
    assert FromTools is FileDiffTool
    assert FileDiffTool in CORE_TOOL_CLASSES
