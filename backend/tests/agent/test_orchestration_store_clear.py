from __future__ import annotations

import json

import pytest

from magi.agent.orchestration import (
    OrchestrationStore,
    TaskOrchestrationState,
    WorkerResult,
)
from magi.agent.runtime.contracts import FactRecord
from magi.agent.task_orchestration_updates import TaskOrchestrationUpdateProcessor


async def test_clear_all_removes_running_terminal_and_worker_result_payloads(
    tmp_path,
) -> None:
    path = tmp_path / "task_orchestrations.json"
    store = OrchestrationStore(path)
    await store.save_orchestration(
        TaskOrchestrationState(
            orchestration_id="orch-running",
            user_id="u1",
            session_id="s1",
            turn_id="turn-running",
            root_user_message="private running question",
            planner="task_agent",
            status="running",
        )
    )
    await store.save_orchestration(
        TaskOrchestrationState(
            orchestration_id="orch-completed",
            user_id="u1",
            session_id="s2",
            turn_id="turn-completed",
            root_user_message="private completed question",
            planner="task_agent",
            status="completed",
            final_response="private final response",
        )
    )
    await store.save_worker_result(
        worker_id="worker-running",
        orchestration_id="orch-running",
        subtask_id="subtask-1",
        worker_result=WorkerResult(summary="private worker result"),
    )
    await store.save_worker_result(
        worker_id="worker-completed",
        orchestration_id="orch-completed",
        subtask_id="subtask-2",
        worker_result=WorkerResult(summary="private completed result"),
    )

    removed = await store.clear_all()

    assert removed == {"orchestrations": 2, "worker_results": 2}
    assert await store.list_orchestrations() == []
    assert await store.get_worker_result("worker-running") is None
    assert await store.get_worker_result("worker-completed") is None
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "orchestrations": {},
        "worker_results": {},
    }


async def test_clear_all_propagates_persistence_failure(tmp_path, monkeypatch) -> None:
    store = OrchestrationStore(tmp_path / "task_orchestrations.json")

    def fail_write(_payload) -> None:  # type: ignore[no-untyped-def]
        raise OSError("disk full")

    monkeypatch.setattr(store, "_write_payload_or_raise", fail_write)

    with pytest.raises(OSError, match="disk full"):
        await store.clear_all()


async def test_late_worker_fact_after_clear_cannot_restore_or_aggregate_chat(
    tmp_path,
) -> None:
    store = OrchestrationStore(tmp_path / "task_orchestrations.json")
    await store.save_orchestration(
        TaskOrchestrationState(
            orchestration_id="orch-old",
            user_id="u1",
            session_id="s1",
            turn_id="turn-old",
            root_user_message="private old question",
            planner="task_agent",
            status="running",
        )
    )
    await store.clear_all()
    host = type("Host", (), {"_orchestration_store": store})()
    processor = TaskOrchestrationUpdateProcessor(host)
    late_fact = FactRecord(
        agent_id="chat:s1",
        agent_type="chat",
        agent_instance_id="s1",
        event_type="WORKER_AGENT_COMPLETED",
        payload={
            "user_id": "u1",
            "session_id": "s1",
            "turn_id": "turn-old",
            "worker_id": "worker-old",
            "stage": "completed",
            "orchestration_id": "orch-old",
            "subtask_id": "subtask-old",
            "worker_result": WorkerResult(summary="late private result").to_dict(),
        },
    )

    result = await processor.process([late_fact])

    assert result.skip_emit is True
    assert result.response == ""
    assert await store.list_orchestrations() == []
    assert await store.get_worker_result("worker-old") is None
