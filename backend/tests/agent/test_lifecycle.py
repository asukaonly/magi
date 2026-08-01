from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.agent.lifecycle import AgentRuntimeModule


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
