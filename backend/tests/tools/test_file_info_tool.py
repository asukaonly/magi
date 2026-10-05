"""Tests for the structured file_info tool."""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.builtin.file_info_tool import FileInfoTool
from magi.tools.schema import ToolExecutionContext


def _context(workspace: str = ".") -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent", workspace=workspace)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["file", "directory"])
async def test_file_info_preserves_unicode_identity_and_reports_actual_metadata(tmp_path, kind):
    target = tmp_path / "示例.txt"
    if kind == "file":
        target.write_bytes(b"hello")
    else:
        target.mkdir()
    result = await FileInfoTool().execute({"path": str(target)}, _context())
    assert result.success
    data = result.data
    assert data["name"] == "示例.txt"
    assert data["kind"] == kind
    assert data["is_file"] is (kind == "file")
    assert data["is_dir"] is (kind == "directory")
    assert data["size"] == target.stat().st_size
    assert "modified" in data and "created" in data
    assert data["mode"].startswith("-" if kind == "file" else "d")
    assert data["mime_type"] == ("text/plain" if kind == "file" else None)


@pytest.mark.asyncio
async def test_file_info_missing_path(tmp_path: Path) -> None:
    tool = FileInfoTool()
    result = await tool.execute({"path": str(tmp_path / "missing")}, _context())

    assert result.success is False
    assert result.error_code == "PATH_NOT_FOUND"
