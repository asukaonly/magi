from __future__ import annotations

import pytest

from magi.bootstrap import backend as backend_module
from magi.core.container import get_container
from magi.llm.lifecycle import RuntimeInitializationDeferred
from magi.skills.service_access import SkillsRuntimeBindings


class _DeferredOrchestrator:
    async def startup(self) -> None:
        raise RuntimeInitializationDeferred(pending_selection=True)


@pytest.mark.asyncio
async def test_initialize_agent_runtime_binds_skills_when_runtime_deferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = get_container()
    container.skill_indexer.reset_override()
    container.skill_loader.reset_override()
    container.skill_runner.reset_override()

    fake_config = type("Config", (), {"features": type("Features", (), {"enable_skills": True})()})()
    bindings = SkillsRuntimeBindings(
        skill_indexer=object(),
        skill_loader=object(),
        skill_runner=object(),
    )

    monkeypatch.setattr(backend_module, "_is_runtime_initialized", lambda: False)
    monkeypatch.setattr(backend_module, "get_config", lambda: fake_config)
    monkeypatch.setattr(backend_module, "build_runtime_modules", lambda context: [])
    monkeypatch.setattr(backend_module, "ModuleLifecycleOrchestrator", lambda modules: _DeferredOrchestrator())
    monkeypatch.setattr(
        "magi.skills.service_access.build_skills_runtime",
        lambda llm_adapter=None: bindings,
    )

    await backend_module.initialize_agent_runtime()

    assert container.skill_indexer() is bindings.skill_indexer
    assert container.skill_loader() is bindings.skill_loader
    assert container.skill_runner() is bindings.skill_runner
    assert container.skill_indexer.overridden
    assert container.skill_loader.overridden
    assert container.skill_runner.overridden

    container.skill_indexer.reset_override()
    container.skill_loader.reset_override()
    container.skill_runner.reset_override()
