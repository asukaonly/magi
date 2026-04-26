"""Tests for the structured file_info tool."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.builtin.file_info_tool import FileInfoTool
from magi.tools.schema import ToolExecutionContext


def _context(workspace: str = ".") -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent", workspace=workspace)


@pytest.mark.asyncio
async def test_file_info_returns_metadata_for_file(tmp_path: Path) -> None:
    target = tmp_path / "示例.txt"
    target.write_text("hello", encoding="utf-8")

    tool = FileInfoTool()
    result = await tool.execute({"path": str(target)}, _context())

    assert result.success is True
    data = result.data
    assert data["name"] == "示例.txt"
    assert data["kind"] == "file"
    assert data["is_file"] is True
    assert data["is_dir"] is False
    assert data["size"] == 5
    assert "modified" in data and "created" in data
    assert data["mode"].startswith("-")


@pytest.mark.asyncio
async def test_file_info_returns_metadata_for_directory(tmp_path: Path) -> None:
    tool = FileInfoTool()
    result = await tool.execute({"path": str(tmp_path)}, _context())

    assert result.success is True
    assert result.data["kind"] == "directory"
    assert result.data["is_dir"] is True
    assert result.data["mime_type"] is None


@pytest.mark.asyncio
async def test_file_info_missing_path(tmp_path: Path) -> None:
    tool = FileInfoTool()
    result = await tool.execute({"path": str(tmp_path / "missing")}, _context())

    assert result.success is False
    assert result.error_code == "PATH_NOT_FOUND"
