"""Tests for the structured file_list tool."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.builtin.file_list_tool import FileListTool
from magi.tools.schema import ToolExecutionContext


def _context(workspace: str = ".") -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent", workspace=workspace)


@pytest.mark.asyncio
async def test_file_list_returns_unicode_names(tmp_path: Path) -> None:
    target = tmp_path / "测试目录"
    target.mkdir()
    (target / "ノート.txt").write_text("hi", encoding="utf-8")
    (target / "readme.md").write_text("# hi", encoding="utf-8")

    tool = FileListTool()
    result = await tool.execute({"path": str(target)}, _context())

    assert result.success is True
    names = {entry["name"] for entry in result.data["entries"]}
    assert {"ノート.txt", "readme.md"} <= names
    for entry in result.data["entries"]:
        assert entry["kind"] in {"file", "directory"}
        assert "size" in entry
        assert "modified" in entry


@pytest.mark.asyncio
async def test_file_list_recursive_respects_max_depth(tmp_path: Path) -> None:
    root = tmp_path / "root"
    deep = root / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "leaf.txt").write_text("x", encoding="utf-8")

    tool = FileListTool()
    result = await tool.execute(
        {"path": str(root), "recursive": True, "max_depth": 2},
        _context(),
    )

    assert result.success is True
    relative_paths = {entry["relative_path"] for entry in result.data["entries"]}
    assert relative_paths == {"a", "a/b"}


@pytest.mark.asyncio
async def test_file_list_truncates_when_max_entries_hit(tmp_path: Path) -> None:
    for index in range(5):
        (tmp_path / f"file_{index}.txt").write_text("x", encoding="utf-8")

    tool = FileListTool()
    result = await tool.execute(
        {"path": str(tmp_path), "max_entries": 3},
        _context(),
    )

    assert result.success is True
    assert result.data["truncated"] is True
    assert result.data["count"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [29, 30])
async def test_file_list_applies_batch_hint_at_homogeneous_file_threshold(tmp_path, count):
    for index in range(count):
        (tmp_path / f"clip_{index}.mkv").write_bytes(b"x")
    result = await FileListTool().execute({"path": str(tmp_path)}, _context())
    assert result.success
    assert {entry["name"] for entry in result.data["entries"]} == {
        f"clip_{index}.mkv" for index in range(count)
    }
    if count < 30:
        assert "batch_hint" not in result.data
    else:
        hint = result.data["batch_hint"]
        assert "batch_create" in hint and ".mkv" in hint and "30" in hint


@pytest.mark.asyncio
async def test_file_list_rejects_missing_path(tmp_path: Path) -> None:
    tool = FileListTool()
    result = await tool.execute({"path": str(tmp_path / "missing")}, _context())

    assert result.success is False
    assert result.error_code == "PATH_NOT_FOUND"


@pytest.mark.asyncio
async def test_file_list_rejects_file_path(tmp_path: Path) -> None:
    file_path = tmp_path / "f.txt"
    file_path.write_text("x", encoding="utf-8")

    tool = FileListTool()
    result = await tool.execute({"path": str(file_path)}, _context())

    assert result.success is False
    assert result.error_code == "NOT_A_DIRECTORY"
