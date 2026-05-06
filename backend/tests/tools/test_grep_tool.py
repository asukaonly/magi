"""
Tests for grep tool path expansion and glob filtering.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from magi.tools.builtin import grep_tool as grep_module
from magi.tools.builtin.grep_tool import GrepTool
from magi.tools.schema import ToolExecutionContext


def _context(workspace: str = "./workspace") -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent", workspace=workspace)


@pytest.mark.asyncio
async def test_grep_expands_home_placeholder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
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
async def test_grep_resolves_relative_path_from_workspace(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "workspace"
    src_dir = workspace_dir / "src"
    src_dir.mkdir(parents=True)
    app_path = src_dir / "app.py"
    app_path.write_text("TARGET_TOKEN\n", encoding="utf-8")

    tool = GrepTool()
    result = await tool.execute(
        {
            "pattern": "TARGET_TOKEN",
            "path": "src",
            "glob": "*.py",
        },
        _context(str(workspace_dir)),
    )

    assert result.success is True
    assert result.data["path"] == str(src_dir)
    assert result.data["match_count"] == 1
    assert Path(result.data["matches"][0]["file"]).resolve() == app_path.resolve()


@pytest.mark.asyncio
async def test_grep_supports_path_glob_filtering(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    nested_src_dir = src_dir / "utils"
    test_dir = tmp_path / "tests"
    src_dir.mkdir()
    nested_src_dir.mkdir()
    test_dir.mkdir()
    src_file = src_dir / "app.py"
    nested_src_file = nested_src_dir / "helper.py"
    test_file = test_dir / "app.py"
    src_file.write_text("TARGET_TOKEN\n", encoding="utf-8")
    nested_src_file.write_text("TARGET_TOKEN\n", encoding="utf-8")
    test_file.write_text("TARGET_TOKEN\n", encoding="utf-8")

    tool = GrepTool()
    result = await tool.execute(
        {
            "pattern": "TARGET_TOKEN",
            "path": str(tmp_path),
            "glob": "src/**/*.py",
            "recursive": True,
        },
        _context(),
    )

    assert result.success is True
    matched_files = {Path(item["file"]).resolve() for item in result.data["matches"]}
    assert src_file.resolve() in matched_files
    assert nested_src_file.resolve() in matched_files
    assert test_file.resolve() not in matched_files


@pytest.mark.asyncio
async def test_grep_excludes_default_large_directories(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    modules_dir = tmp_path / "node_modules"
    src_dir.mkdir()
    modules_dir.mkdir()
    src_file = src_dir / "a.py"
    module_file = modules_dir / "b.py"
    src_file.write_text("TOKEN\n", encoding="utf-8")
    module_file.write_text("TOKEN\n", encoding="utf-8")

    tool = GrepTool()
    result = await tool.execute(
        {
            "pattern": "TOKEN",
            "path": str(tmp_path),
            "glob": "**/*.py",
            "recursive": True,
        },
        _context(),
    )

    assert result.success is True
    matched_files = {Path(item["file"]).resolve() for item in result.data["matches"]}
    assert src_file.resolve() in matched_files
    assert module_file.resolve() not in matched_files


@pytest.mark.asyncio
async def test_grep_falls_back_to_python_when_ripgrep_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(grep_module, "_resolve_ripgrep_executable", lambda: None)
    source_file = tmp_path / "app.py"
    source_file.write_text("alpha\nTARGET_TOKEN\nomega\n", encoding="utf-8")

    tool = GrepTool()
    result = await tool.execute(
        {
            "pattern": "target_token",
            "path": str(tmp_path),
            "glob": "*.py",
            "ignore_case": True,
            "context_lines": 1,
        },
        _context(),
    )

    assert result.success is True
    assert result.data["engine"] == "python"
    assert result.data["match_count"] == 1
    match = result.data["matches"][0]
    assert Path(match["file"]).resolve() == source_file.resolve()
    assert match["content"] == "TARGET_TOKEN"
    assert match["context_before"] == [{"line_number": 1, "content": "alpha"}]
    assert match["context_after"] == [{"line_number": 3, "content": "omega"}]


@pytest.mark.asyncio
async def test_grep_uses_ripgrep_json_output_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "app.py"
    source_file.write_text("alpha\nTARGET_TOKEN\nomega\n", encoding="utf-8")
    fake_script = tmp_path / "fake_rg.py"
    fake_script.write_text(
        "import json\n"
        "import os\n"
        "path = os.environ['MAGI_FAKE_RG_FILE']\n"
        "messages = [\n"
        "    {'type': 'begin', 'data': {'path': {'text': path}}},\n"
        "    {\n"
        "        'type': 'match',\n"
        "        'data': {\n"
        "            'path': {'text': path},\n"
        "            'lines': {'text': 'TARGET_TOKEN\\n'},\n"
        "            'line_number': 2,\n"
        "        },\n"
        "    },\n"
        "    {'type': 'summary', 'data': {}},\n"
        "]\n"
        "for message in messages:\n"
        "    print(json.dumps(message), flush=True)\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        fake_rg = tmp_path / "fake-rg.cmd"
        fake_rg.write_text(f'@echo off\r\n"{sys.executable}" "{fake_script}" %*\r\n', encoding="utf-8")
    else:
        fake_rg = tmp_path / "fake-rg"
        fake_rg.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake_script}" "$@"\n', encoding="utf-8")
        fake_rg.chmod(0o755)

    monkeypatch.setenv("MAGI_FAKE_RG_FILE", str(source_file))
    monkeypatch.setattr(grep_module, "_resolve_ripgrep_executable", lambda: str(fake_rg))

    tool = GrepTool()
    result = await tool.execute(
        {
            "pattern": "TARGET_TOKEN",
            "path": str(tmp_path),
            "glob": "*.py",
            "context_lines": 1,
        },
        _context(),
    )

    assert result.success is True
    assert result.data["engine"] == "ripgrep"
    assert result.data["match_count"] == 1
    match = result.data["matches"][0]
    assert Path(match["file"]).resolve() == source_file.resolve()
    assert match["line_number"] == 2
    assert match["content"] == "TARGET_TOKEN"
    assert match["context_before"] == [{"line_number": 1, "content": "alpha"}]
    assert match["context_after"] == [{"line_number": 3, "content": "omega"}]
