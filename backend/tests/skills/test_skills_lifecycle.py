from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.skills.lifecycle import SkillsModule


@pytest.mark.asyncio
async def test_skills_module_populates_shared_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    context = RuntimeBootstrapContext()
    context.core.config = SimpleNamespace(features=SimpleNamespace(enable_skills=True))
    context.llm.llm_adapter = object()

    fake_indexer = object()
    fake_loader = object()
    fake_runner = object()

    monkeypatch.setattr(
        "magi.skills.lifecycle.build_skills_runtime",
        lambda llm_adapter=None: SimpleNamespace(
            skill_indexer=fake_indexer,
            skill_loader=fake_loader,
            skill_runner=fake_runner,
        ),
    )

    module = SkillsModule(context)
    await module.init()

    assert context.skills.skill_indexer is fake_indexer
    assert context.skills.skill_loader is fake_loader
    assert context.skills.skill_runner is fake_runner