"""Tests for persisted typed worker results."""

from types import SimpleNamespace

import pytest

from magi.agent.orchestration import (
    OrchestrationStore,
    SubtaskDefinition,
    TaskOrchestrationState,
    WorkerArtifact,
    WorkerResult,
    WorkerVerification,
)
from magi.agent.task_orchestration_updates import (
    TaskOrchestrationUpdateProcessor,
    _WorkerUpdateContext,
    _worker_result_can_complete,
)


@pytest.mark.asyncio
async def test_worker_result_records_survive_store_round_trip(tmp_path) -> None:
    store = OrchestrationStore(tmp_path / "orchestrations.json")
    result = WorkerResult(
        summary="Inventory ready",
        records=[{"path": "C:/Inbox/a.pdf", "category": "documents"}],
        artifacts=[WorkerArtifact(path="C:/Inbox/a.pdf", operation="modified")],
        verification=[
            WorkerVerification(
                command="verify workbook",
                status="passed",
                detail="All expected rows were present",
            )
        ],
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
    assert restored.artifacts == result.artifacts
    assert restored.verification == result.verification


@pytest.mark.parametrize(
    "payload",
    [
        {
            "summary": "Malformed artifact",
            "artifacts": [{"path": True, "operation": "modified"}],
            "verification": [{"command": "pytest -q", "status": "passed", "detail": "ok"}],
        },
        {
            "summary": "Malformed verification",
            "artifacts": [{"path": "src/app.py", "operation": "modified"}],
            "verification": [{"command": 42, "status": "passed", "detail": "ok"}],
        },
    ],
)
def test_worker_result_deserialization_does_not_coerce_coding_evidence(
    payload: dict[str, object],
) -> None:
    restored = WorkerResult.from_dict(payload)

    assert not (restored.artifacts and restored.verification)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "summary": "Missing status",
            "artifacts": [{"path": "src/app.py", "operation": "modified"}],
            "verification": [{"command": "pytest -q", "status": "passed", "detail": "ok"}],
        },
        {
            "result_status": "partial",
            "summary": {"text": "not a string"},
            "artifacts": [{"path": "src/app.py", "operation": "modified"}],
            "verification": [{"command": "pytest -q", "status": "passed", "detail": "ok"}],
            "gaps": [42],
            "next_steps": [True],
        },
        {
            "result_status": "failed",
            "summary": "Blocked",
            "failure_reason": {"code": "BLOCKED"},
        },
        {
            "result_status": "failed",
            "summary": "",
            "findings": [],
            "evidence": [],
            "artifacts": [],
            "verification": [],
            "gaps": [],
            "next_steps": [],
            "failure_reason": "BLOCKED",
        },
    ],
)
def test_persisted_coding_text_fields_are_not_coerced_into_completion(
    payload: dict[str, object],
) -> None:
    worker_result = WorkerResult.from_dict(payload)
    subtask = SubtaskDefinition(
        subtask_id="subtask-1",
        description="Update parser",
        subagent_type="Coding",
        prompt="Update the parser",
    )

    assert _worker_result_can_complete(subtask, worker_result) is False


@pytest.mark.parametrize(
    ("field_name", "invalid_item"),
    [
        ("artifacts", {"path": True, "operation": "modified"}),
        ("verification", {"command": 42, "status": "passed", "detail": "ok"}),
        ("gaps", 42),
        ("next_steps", ""),
    ],
)
def test_persisted_coding_result_rejects_mixed_valid_and_invalid_items(
    field_name: str,
    invalid_item: object,
) -> None:
    payload: dict[str, object] = {
        "result_status": "success",
        "summary": "Parser updated",
        "artifacts": [{"path": "src/app.py", "operation": "modified"}],
        "verification": [{"command": "pytest -q", "status": "passed", "detail": "ok"}],
        "findings": [],
        "evidence": [],
        "records": [],
        "gaps": ["No known gaps"],
        "next_steps": ["Review the change"],
    }
    assert isinstance(payload[field_name], list)
    payload[field_name].append(invalid_item)
    worker_result = WorkerResult.from_dict(payload)
    subtask = SubtaskDefinition(
        subtask_id="subtask-1",
        description="Update parser",
        subagent_type="Coding",
        prompt="Update the parser",
    )

    assert worker_result.artifacts
    assert worker_result.verification
    assert _worker_result_can_complete(subtask, worker_result) is False
    restored = WorkerResult.from_dict(worker_result.to_dict())
    assert _worker_result_can_complete(subtask, restored) is False


@pytest.mark.parametrize(
    "payload_update",
    [
        {"findings": "invalid"},
        {"evidence": None},
        {"records": [42]},
        {"records": [{}] * 501},
    ],
)
def test_persisted_coding_result_rejects_invalid_common_envelope(
    payload_update: dict[str, object],
) -> None:
    payload: dict[str, object] = {
        "result_status": "success",
        "summary": "Parser updated",
        "findings": [],
        "evidence": [],
        "artifacts": [{"path": "src/app.py", "operation": "modified"}],
        "verification": [{"command": "pytest -q", "status": "passed", "detail": "ok"}],
        "records": [],
        "gaps": [],
        "next_steps": [],
    }
    payload.update(payload_update)
    worker_result = WorkerResult.from_dict(payload)
    subtask = SubtaskDefinition(
        subtask_id="subtask-1",
        description="Update parser",
        subagent_type="Coding",
        prompt="Update the parser",
    )

    assert _worker_result_can_complete(subtask, worker_result) is False
    restored = WorkerResult.from_dict(worker_result.to_dict())
    assert _worker_result_can_complete(subtask, restored) is False


@pytest.mark.parametrize("missing_field", ["findings", "evidence"])
def test_persisted_coding_result_requires_common_envelope_fields(
    missing_field: str,
) -> None:
    payload: dict[str, object] = {
        "result_status": "success",
        "summary": "Parser updated",
        "findings": [],
        "evidence": [],
        "artifacts": [{"path": "src/app.py", "operation": "modified"}],
        "verification": [{"command": "pytest -q", "status": "passed", "detail": "ok"}],
        "records": [],
        "gaps": [],
        "next_steps": [],
    }
    payload.pop(missing_field)
    worker_result = WorkerResult.from_dict(payload)
    subtask = SubtaskDefinition(
        subtask_id="subtask-1",
        description="Update parser",
        subagent_type="Coding",
        prompt="Update the parser",
    )

    assert _worker_result_can_complete(subtask, worker_result) is False


@pytest.mark.parametrize(
    "worker_result",
    [
        WorkerResult(summary="Invalid status", result_status="unknown"),
        WorkerResult(summary="Missing failure reason", result_status="failed"),
        WorkerResult(
            summary="Malformed artifact",
            artifacts=[WorkerArtifact(path="", operation="modified")],
            verification=[WorkerVerification(command="pytest -q", status="passed", detail="ok")],
        ),
        WorkerResult(
            summary="Malformed partial",
            result_status="partial",
            artifacts=[WorkerArtifact(path="src/app.py", operation="modified")],
            verification=[WorkerVerification(command="pytest -q", status="passed", detail="ok")],
            gaps=[""],
            next_steps=["Retry the missing change"],
        ),
    ],
)
def test_invalid_coding_result_cannot_reach_terminal_success(
    worker_result: WorkerResult,
) -> None:
    subtask = SubtaskDefinition(
        subtask_id="subtask-1",
        description="Update parser",
        subagent_type="Coding",
        prompt="Update the parser",
    )

    assert _worker_result_can_complete(subtask, worker_result) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("result_status", ["success", "partial"])
async def test_persisted_coding_result_without_evidence_cannot_complete(
    result_status: str,
) -> None:
    legacy_result = WorkerResult(
        summary="Legacy plain-text completion",
        result_status=result_status,
        gaps=["Legacy result has no structured evidence"],
        next_steps=["Run the Coding worker again"],
    )

    class _Store:
        async def get_worker_result(self, worker_id: str) -> WorkerResult | None:
            return legacy_result if worker_id == "worker-1" else None

    subtask = SubtaskDefinition(
        subtask_id="subtask-1",
        description="Update parser",
        subagent_type="Coding",
        prompt="Update the parser",
        status="running",
        worker_id="worker-1",
    )
    state = TaskOrchestrationState(
        orchestration_id="orchestration-1",
        user_id="user-1",
        session_id="session-1",
        root_user_message="Update the parser",
        planner="task_agent",
        subtasks=[subtask],
    )
    payload = SimpleNamespace(
        worker_result=None,
        error=None,
        error_text=None,
        tool_failures=[],
    )
    context = _WorkerUpdateContext(
        event_type="WORKER_AGENT_COMPLETED",
        payload=payload,
        state=state,
        subtask=subtask,
        payload_worker_id="worker-1",
    )
    processor = TaskOrchestrationUpdateProcessor(SimpleNamespace(_orchestration_store=_Store()))

    await processor._mark_subtask_completed(context)

    assert subtask.status == "failed"
    assert subtask.failure_reason == "INVALID_WORKER_RESULT"
    assert subtask.worker_result is legacy_result
