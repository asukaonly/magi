"""
Tests for file_read tool path handling.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.schema import ToolExecutionContext


def _context(workspace: str = "./workspace") -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent", workspace=workspace)


@pytest.mark.asyncio
async def test_file_read_expands_home_placeholder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    readme_path = project_dir / "README.md"
    readme_path.write_text("hello magi\n", encoding="utf-8")

    tool = FileReadTool()
    result = await tool.execute({"path": "~/project/README.md"}, _context())

    assert result.success is True
    assert result.data["path"] == str(readme_path)
    assert result.data["content"] == "hello magi\n"


@pytest.mark.asyncio
async def test_file_read_resolves_relative_path_from_workspace(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    docs_dir = workspace_dir / "docs"
    docs_dir.mkdir(parents=True)
    readme_path = docs_dir / "README.md"
    readme_path.write_text("workspace doc\n", encoding="utf-8")

    tool = FileReadTool()
    result = await tool.execute({"path": "docs/README.md"}, _context(str(workspace_dir)))

    assert result.success is True
    assert result.data["path"] == str(readme_path)
    assert result.data["content"] == "workspace doc\n"
