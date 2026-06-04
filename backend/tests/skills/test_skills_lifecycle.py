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
    captured: dict[str, object] = {}

    def _fake_build_skills_runtime(llm_adapter=None, permission_gateway_provider=None, *, tool_registry):
        captured["llm_adapter"] = llm_adapter
        captured["permission_gateway_provider"] = permission_gateway_provider
        captured["tool_registry"] = tool_registry
        return SimpleNamespace(
            skill_indexer=fake_indexer,
            skill_loader=fake_loader,
            skill_runner=fake_runner,
        )

    monkeypatch.setattr(
        "magi.skills.lifecycle.build_skills_runtime",
        _fake_build_skills_runtime,
    )

    fake_registry = object()
    module = SkillsModule(context, tool_registry=fake_registry)
    await module.init()

    assert context.skills.skill_indexer is fake_indexer
    assert context.skills.skill_loader is fake_loader
    assert context.skills.skill_runner is fake_runner
    assert captured["llm_adapter"] is context.llm.llm_adapter
    assert callable(captured["permission_gateway_provider"])
    assert captured["tool_registry"] is fake_registry