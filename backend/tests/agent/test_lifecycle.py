from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.agent.lifecycle import AgentRuntimeModule
from magi.agent.task_agents import DefaultTaskAgent
from magi.bootstrap.context import RuntimeBootstrapContext


def test_default_agent_factory_wiring_matches_runtime_contract() -> None:
    """Build the non-chat factory through the production composition seam."""

    context = RuntimeBootstrapContext()
    context.agent_runtime.sensor_ingestion_gateway = object()
    module = AgentRuntimeModule(
        context,
        create_chat_agent_factory=lambda **_kwargs: lambda _agent_id: None,
        chat_read_service_factory=lambda *_args, **_kwargs: None,
        build_timeline_handler=lambda *_args, **_kwargs: None,
        global_clear_pending=AsyncMock(return_value=False),
    )
    deps = SimpleNamespace(
        config=object(),
        llm_adapter=object(),
        llm_pool=object(),
        unified_memory=object(),
        plugin_manager=object(),
        sensor_registry=object(),
    )

    factory = module._build_default_agent_factory(deps)
    agent = factory("custom", "worker-1")

    assert isinstance(agent, DefaultTaskAgent)
    assert agent.runtime_key == "custom:worker-1"


@pytest.mark.asyncio
async def test_interrupted_global_clear_discards_batch_manifests_before_resume(
    monkeypatch,
) -> None:
    global_clear_pending = AsyncMock(return_value=True)
    batch_store = SimpleNamespace(
        clear_all=AsyncMock(return_value={"batch_jobs": 2, "batch_items": 7})
    )
    resume_running_jobs = AsyncMock(return_value=2)
    monkeypatch.setattr(
        "magi.agent.batch.store.default_batch_store",
        lambda: batch_store,
    )
    monkeypatch.setattr(
        "magi.agent.batch.driver.BatchDriver.resume_running_jobs",
        resume_running_jobs,
    )

    await AgentRuntimeModule._resume_batch_jobs(
        SimpleNamespace(manager=SimpleNamespace()),
        global_clear_pending=global_clear_pending,
    )

    global_clear_pending.assert_awaited_once_with()
    batch_store.clear_all.assert_awaited_once_with()
    resume_running_jobs.assert_not_awaited()


@pytest.mark.asyncio
async def test_normal_startup_resumes_batch_manifests(monkeypatch) -> None:
    global_clear_pending = AsyncMock(return_value=False)
    batch_store = SimpleNamespace(clear_all=AsyncMock())
    resume_running_jobs = AsyncMock(return_value=2)
    monkeypatch.setattr(
        "magi.agent.batch.store.default_batch_store",
        lambda: batch_store,
    )
    monkeypatch.setattr(
        "magi.agent.batch.driver.BatchDriver.resume_running_jobs",
        resume_running_jobs,
    )

    manager = SimpleNamespace()
    await AgentRuntimeModule._resume_batch_jobs(
        SimpleNamespace(manager=manager),
        global_clear_pending=global_clear_pending,
    )

    global_clear_pending.assert_awaited_once_with()
    batch_store.clear_all.assert_not_awaited()
    resume_running_jobs.assert_awaited_once_with()
