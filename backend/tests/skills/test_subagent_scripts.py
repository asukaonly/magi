"""Tests for skill subagent script execution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from magi.skills.schema import SkillContent, SkillFrontmatter
from magi.skills.subagent import SkillSubagent


def _make_skill(script_path: Path | None = None) -> SkillContent:
    scripts = []
    if script_path is not None:
        scripts.append({"name": "hello", "path": str(script_path)})
    return SkillContent(
        name="script-skill",
        frontmatter=SkillFrontmatter(name="script-skill", description="Script skill"),
        prompt_template="body",
        supporting_data={"scripts": scripts},
        source_file=None,
    )


@pytest.mark.asyncio
async def test_execute_script_returns_not_found_for_missing_script() -> None:
    subagent = SkillSubagent(skill=_make_skill(), llm_adapter=MagicMock())

    result = await subagent.execute_script("missing")

    assert result["success"] is False
    assert result["error"] == "Script not found: missing"
    assert result["stdout"] == ""
    assert result["stderr"] == ""
    assert result["return_code"] == -1


@pytest.mark.asyncio
async def test_execute_script_runs_script_and_marks_it_executable(tmp_path: Path) -> None:
    script_path = tmp_path / "hello.py"
    script_path.write_text(
        "#!/usr/bin/env python3\n" "import sys\n" "print(f'hello {sys.argv[1]}')\n",
        encoding="utf-8",
    )
    script_path.chmod(0o644)
    subagent = SkillSubagent(skill=_make_skill(script_path), llm_adapter=MagicMock())

    result = await subagent.execute_script("hello", args=["magi"], timeout=5)

    assert result["success"] is True
    assert result["stdout"] == "hello magi\n"
    assert result["stderr"] == ""
    assert result["return_code"] == 0
    assert script_path.stat().st_mode & 0o111
