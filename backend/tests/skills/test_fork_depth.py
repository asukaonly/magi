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
async def test_fork_depth_resets_on_exit(monkeypatch):
    monkeypatch.setattr(runner_module, "MAX_FORK_DEPTH", 5)
    skill = _make_skill()
    loader = type("Loader", (), {"load_skill": lambda _self, _name: skill})()

    captured_request: dict[str, object] = {}

    class _Orchestrator:
        async def run(self, request):  # type: ignore[no-untyped-def]
            captured_request.update(request)
            return type(
                "Outcome",
                (),
                {"succeeded": True, "content": "ok", "failure_reason": None},
            )()

    runner = SkillRunner(
        loader=loader,  # type: ignore[arg-type]
        llm_adapter=object(),  # type: ignore[arg-type]
        orchestrator_factory=lambda **_kwargs: _Orchestrator(),
        agent_run_request_factory=lambda **kwargs: kwargs,
    )
    before = runner_module._fork_depth.get()
    result = await runner.execute("deep")
    after = runner_module._fork_depth.get()
    assert result.success is True
    assert before == after
    assert "system_prompt" not in captured_request
    assert "body" in str(captured_request["working_context"])
