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
    fake_executor = object()

    monkeypatch.setattr("magi.skills.lifecycle.init_skills_module", lambda llm_adapter=None: None)
    monkeypatch.setattr("magi.skills.lifecycle.get_skill_indexer", lambda: fake_indexer)
    monkeypatch.setattr("magi.skills.lifecycle.get_skill_loader", lambda: fake_loader)
    monkeypatch.setattr("magi.skills.lifecycle.get_skill_executor", lambda: fake_executor)

    module = SkillsModule(context)
    await module.init()

    assert context.skills.skill_indexer is fake_indexer
    assert context.skills.skill_loader is fake_loader
    assert context.skills.skill_executor is fake_executor