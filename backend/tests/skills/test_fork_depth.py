"""Verify the fork-mode recursion guard rejects skills past MAX_FORK_DEPTH."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from magi.skills import subagent as subagent_module
from magi.skills.schema import SkillContent, SkillFrontmatter
from magi.skills.subagent import SkillSubagent


def _make_skill() -> SkillContent:
    return SkillContent(
        name="deep",
        frontmatter=SkillFrontmatter(name="deep", description="d"),
        prompt_template="body",
        supporting_data={},
        source_file=None,
    )


@pytest.mark.asyncio
async def test_fork_depth_rejects_past_limit(monkeypatch):
    """Saturate the contextvar and confirm the next execute is denied."""
    monkeypatch.setattr(subagent_module, "MAX_FORK_DEPTH", 2)
    # Pre-set the contextvar to the limit so the next call trips it.
    token = subagent_module._fork_depth.set(2)
    try:
        skill = _make_skill()
        sub = SkillSubagent(skill=skill, llm_adapter=MagicMock())
        result = await sub.execute(user_message="hi", system_prompt="sys")
        assert result.success is False
        assert "MAX_FORK_DEPTH" in (result.error or "")
    finally:
        subagent_module._fork_depth.reset(token)


@pytest.mark.asyncio
async def test_fork_depth_resets_on_exit(monkeypatch):
    """After a successful execute, the depth contextvar must be back to its pre-call value."""
    monkeypatch.setattr(subagent_module, "MAX_FORK_DEPTH", 5)

    skill = _make_skill()
    sub = SkillSubagent(skill=skill, llm_adapter=MagicMock())

    # Stub out the actual heavy paths so execute returns quickly.
    async def fake_agent_run(**kwargs):
        return "ok"

    sub._execute_agent_run = fake_agent_run  # type: ignore[method-assign]

    before = subagent_module._fork_depth.get()
    result = await sub.execute(user_message="hi", system_prompt="sys")
    after = subagent_module._fork_depth.get()
    assert result.success is True
    assert before == after
