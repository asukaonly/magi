"""
Tests for grep tool path expansion and glob filtering.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.builtin.grep_tool import GrepTool
from magi.tools.schema import ToolExecutionContext


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent")


@pytest.mark.asyncio
async def test_grep_expands_home_placeholder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "notes.txt").write_text("hello magi\n", encoding="utf-8")

    tool = GrepTool()
    result = await tool.execute(
        {
            "pattern": "hello",
            "path": "~/project",
            "glob": "*.txt",
        },
        _context(),
    )

    assert result.success is True
    assert result.data["path"] == str(project_dir)
    assert result.data["match_count"] == 1
    assert result.data["matches"][0]["content"] == "hello magi"


@pytest.mark.asyncio
async def test_grep_supports_path_glob_filtering(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    test_dir = tmp_path / "tests"
    src_dir.mkdir()
    test_dir.mkdir()
    src_file = src_dir / "app.py"
    test_file = test_dir / "app.py"
    src_file.write_text("TARGET_TOKEN\n", encoding="utf-8")
    test_file.write_text("TARGET_TOKEN\n", encoding="utf-8")

    tool = GrepTool()
    result = await tool.execute(
        {
            "pattern": "TARGET_TOKEN",
            "path": str(tmp_path),
            "glob": "src/*.py",
            "recursive": True,
        },
        _context(),
    )

    assert result.success is True
    matched_files = {Path(item["file"]).resolve() for item in result.data["matches"]}
    assert src_file.resolve() in matched_files
    assert test_file.resolve() not in matched_files
