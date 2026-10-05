"""Verify fork skills share one bounded child-run recursion guard."""

from __future__ import annotations

import pytest

from magi.skills import runner as runner_module
from magi.skills.runner import SkillRunner
from magi.skills.schema import SkillContent, SkillFrontmatter


def _make_skill() -> SkillContent:
    return SkillContent(
        name="deep",
        frontmatter=SkillFrontmatter(name="deep", description="d", context="fork"),
        prompt_template="body",
        supporting_data={},
        source_file=None,
    )


@pytest.mark.asyncio
async def test_fork_depth_rejects_past_limit(monkeypatch):
    monkeypatch.setattr(runner_module, "MAX_FORK_DEPTH", 2)
    token = runner_module._fork_depth.set(2)
    try:
        skill = _make_skill()
        loader = type("Loader", (), {"load_skill": lambda _self, _name: skill})()
        runner = SkillRunner(
            loader=loader,  # type: ignore[arg-type]
            llm_adapter=object(),  # type: ignore[arg-type]
            orchestrator_factory=lambda **_kwargs: object(),
            agent_run_request_factory=lambda **kwargs: kwargs,
        )
        result = await runner.execute("deep")
        assert result.success is False
        assert "MAX_FORK_DEPTH" in (result.error or "")
    finally:
        runner_module._fork_depth.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
async def test_fork_depth_increments_and_restores_after_every_exit(monkeypatch, outcome):
    import asyncio
    from types import SimpleNamespace

    monkeypatch.setattr(runner_module, "MAX_FORK_DEPTH", 5)
    skill = _make_skill()
    loader = type("Loader", (), {"load_skill": lambda _self, _name: skill})()
    seen = []

    class Orchestrator:
        async def run(self, request):
            seen.append((runner_module._fork_depth.get(), request))
            if outcome == "cancelled":
                raise asyncio.CancelledError()
            if outcome == "failure":
                raise RuntimeError("child failed")
            return SimpleNamespace(succeeded=True, content="ok", failure_reason=None)

    runner = SkillRunner(
        loader=loader,
        llm_adapter=object(),
        orchestrator_factory=lambda **kwargs: Orchestrator(),
        agent_run_request_factory=lambda **kwargs: kwargs,
    )
    token = runner_module._fork_depth.set(2)
    try:
        if outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await runner.execute("deep")
        else:
            result = await runner.execute("deep")
            assert result.success is (outcome == "success")
            if outcome == "failure":
                assert result.error == "child failed"
        assert runner_module._fork_depth.get() == 2
        assert len(seen) == 1 and seen[0][0] == 3
        assert "system_prompt" not in seen[0][1]
        assert "body" in str(seen[0][1]["working_context"])
    finally:
        runner_module._fork_depth.reset(token)
