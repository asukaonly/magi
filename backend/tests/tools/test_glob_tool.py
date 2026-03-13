"""
Tests for glob tool path handling and pattern matching.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.builtin.glob_tool import GlobTool
from magi.tools.schema import ToolExecutionContext


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent")


@pytest.mark.asyncio
async def test_glob_expands_home_placeholder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "main.py").write_text("print('ok')\n", encoding="utf-8")

    tool = GlobTool()
    result = await tool.execute({"pattern": "*.py", "path": "~/project"}, _context())

    assert result.success is True
    assert result.data["base_path"] == str(project_dir)
    assert result.data["count"] == 1
    assert result.data["matches"][0]["name"] == "main.py"


@pytest.mark.asyncio
async def test_glob_supports_path_pattern_with_recursive_matching(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    nested_dir = src_dir / "utils"
    src_dir.mkdir()
    nested_dir.mkdir()
    (src_dir / "app.py").write_text("app = 1\n", encoding="utf-8")
    (nested_dir / "helper.py").write_text("helper = 1\n", encoding="utf-8")
    (tmp_path / "top.py").write_text("top = 1\n", encoding="utf-8")

    tool = GlobTool()
    result = await tool.execute({"pattern": "src/**/*.py", "path": str(tmp_path)}, _context())

    assert result.success is True
    paths = {Path(item["path"]).resolve() for item in result.data["matches"]}
    assert (src_dir / "app.py").resolve() in paths
    assert (nested_dir / "helper.py").resolve() in paths
    assert (tmp_path / "top.py").resolve() not in paths


@pytest.mark.asyncio
async def test_glob_hides_dot_paths_by_default(tmp_path: Path) -> None:
    visible = tmp_path / "visible.py"
    hidden_dir = tmp_path / ".hidden"
    hidden_file = hidden_dir / "secret.py"
    visible.write_text("visible = True\n", encoding="utf-8")
    hidden_dir.mkdir()
    hidden_file.write_text("secret = True\n", encoding="utf-8")

    tool = GlobTool()
    result = await tool.execute({"pattern": "**/*.py", "path": str(tmp_path)}, _context())

    assert result.success is True
    paths = {Path(item["path"]).resolve() for item in result.data["matches"]}
    assert visible.resolve() in paths
    assert hidden_file.resolve() not in paths


@pytest.mark.asyncio
async def test_glob_can_include_dot_paths_when_requested(tmp_path: Path) -> None:
    hidden_dir = tmp_path / ".hidden"
    hidden_dir.mkdir()
    hidden_file = hidden_dir / "secret.py"
    hidden_file.write_text("secret = True\n", encoding="utf-8")

    tool = GlobTool()
    result = await tool.execute(
        {
            "pattern": "**/*.py",
            "path": str(tmp_path),
            "include_hidden": True,
        },
        _context(),
    )

    assert result.success is True
    paths = {Path(item["path"]).resolve() for item in result.data["matches"]}
    assert hidden_file.resolve() in paths


@pytest.mark.asyncio
async def test_glob_defaults_to_non_recursive_for_simple_patterns(tmp_path: Path) -> None:
    top_file = tmp_path / "top.py"
    nested_dir = tmp_path / "nested"
    nested_file = nested_dir / "deep.py"
    top_file.write_text("top = True\n", encoding="utf-8")
    nested_dir.mkdir()
    nested_file.write_text("deep = True\n", encoding="utf-8")

    tool = GlobTool()
    result = await tool.execute({"pattern": "*.py", "path": str(tmp_path)}, _context())

    assert result.success is True
    paths = {Path(item["path"]).resolve() for item in result.data["matches"]}
    assert top_file.resolve() in paths
    assert nested_file.resolve() not in paths


@pytest.mark.asyncio
async def test_glob_excludes_default_large_directories(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    modules_dir = tmp_path / "node_modules"
    src_dir.mkdir()
    modules_dir.mkdir()
    src_file = src_dir / "app.js"
    module_file = modules_dir / "dep.js"
    src_file.write_text("console.log('app')\n", encoding="utf-8")
    module_file.write_text("console.log('dep')\n", encoding="utf-8")

    tool = GlobTool()
    result = await tool.execute(
        {
            "pattern": "**/*.js",
            "path": str(tmp_path),
            "recursive": True,
        },
        _context(),
    )

    assert result.success is True
    paths = {Path(item["path"]).resolve() for item in result.data["matches"]}
    assert src_file.resolve() in paths
    assert module_file.resolve() not in paths
