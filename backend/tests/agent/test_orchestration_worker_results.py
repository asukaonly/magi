"""Tests for persisted typed worker results."""

import pytest

from magi.agent.orchestration import OrchestrationStore, WorkerResult


@pytest.mark.asyncio
async def test_worker_result_records_survive_store_round_trip(tmp_path) -> None:
    store = OrchestrationStore(tmp_path / "orchestrations.json")
    result = WorkerResult(
        summary="Inventory ready",
        records=[{"path": "C:/Inbox/a.pdf", "category": "documents"}],
    )

    await store.save_worker_result(
        worker_id="worker-1",
        orchestration_id="orchestration-1",
        subtask_id="subtask-1",
        worker_result=result,
    )

    restored = await store.get_worker_result("worker-1")

    assert restored is not None
    assert restored.records == result.records
