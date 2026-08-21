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

    async def _reserve_llm_call() -> None:
        return None

    def _fake_build_skills_runtime(
        llm_adapter=None,
        permission_gateway_provider=None,
        active_model_provider=None,
        scenario_llm_pool=None,
        *,
        tool_registry,
        orchestrator_factory=None,
        engine_run_input_factory=None,
        llm_call_reserver=None,
    ):
        captured["llm_adapter"] = llm_adapter
        captured["permission_gateway_provider"] = permission_gateway_provider
        captured["active_model_provider"] = active_model_provider
        captured["scenario_llm_pool"] = scenario_llm_pool
        captured["tool_registry"] = tool_registry
        captured["orchestrator_factory"] = orchestrator_factory
        captured["engine_run_input_factory"] = engine_run_input_factory
        captured["llm_call_reserver"] = llm_call_reserver
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
    fake_orchestrator_factory = object()
    fake_engine_run_input_factory = object()
    module = SkillsModule(
        context,
        tool_registry=fake_registry,
        orchestrator_factory=fake_orchestrator_factory,
        engine_run_input_factory=fake_engine_run_input_factory,
        llm_call_reserver=_reserve_llm_call,
    )
    await module.init()

    assert context.skills.skill_indexer is fake_indexer
    assert context.skills.skill_loader is fake_loader
    assert context.skills.skill_runner is fake_runner
    assert captured["llm_adapter"] is context.llm.llm_adapter
    assert callable(captured["permission_gateway_provider"])
    assert captured["tool_registry"] is fake_registry
    assert captured["orchestrator_factory"] is fake_orchestrator_factory
    assert captured["engine_run_input_factory"] is fake_engine_run_input_factory
    assert captured["llm_call_reserver"] is _reserve_llm_call
