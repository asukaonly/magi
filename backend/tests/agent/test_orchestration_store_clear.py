from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from magi.agent.orchestration import (
    OrchestrationStore,
    TaskOrchestrationState,
    WorkerResult,
)
from magi.agent.runtime.contracts import FactRecord
from magi.agent.task_orchestration_updates import TaskOrchestrationUpdateProcessor
from magi.utils import file_io


def _create_atomic_temp_file(target: Path, content: str) -> Path:
    fd, raw_path = tempfile.mkstemp(
        dir=target.parent,
        prefix=file_io.atomic_write_temp_prefix(target),
        suffix=".tmp",
    )
    path = Path(raw_path)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


async def test_normal_write_uses_owned_atomic_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "task_orchestrations.json"
    store = OrchestrationStore(path)
    temp_paths: list[Path] = []
    original_replace = file_io.os.replace

    def capture_replace(source: str, destination: Path) -> None:
        temp_paths.append(Path(source))
        original_replace(source, destination)

    monkeypatch.setattr(file_io.os, "replace", capture_replace)

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

    assert len(temp_paths) == 1
    assert temp_paths[0].name.startswith(file_io.atomic_write_temp_prefix(path))
    assert temp_paths[0].name.endswith(".tmp")
    assert not temp_paths[0].exists()
    assert path.exists()


async def test_clear_all_removes_crash_leftover_owned_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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

    with monkeypatch.context() as crash:

        def simulate_crash(*_args) -> None:  # type: ignore[no-untyped-def]
            raise OSError("crash")

        crash.setattr(file_io.os, "replace", simulate_crash)
        crash.setattr(file_io.os, "unlink", simulate_crash)
        await store.save_worker_result(
            worker_id="worker-crashed",
            orchestration_id="orch-running",
            subtask_id="subtask-1",
            worker_result=WorkerResult(summary="private crash leftover"),
        )

    leftovers = [
        candidate
        for candidate in tmp_path.iterdir()
        if candidate.name.startswith(file_io.atomic_write_temp_prefix(path))
    ]
    assert len(leftovers) == 1
    assert "private crash leftover" in leftovers[0].read_text(encoding="utf-8")

    await store.clear_all()

    assert not leftovers[0].exists()


async def test_clear_all_propagates_owned_temp_deletion_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "task_orchestrations.json"
    store = OrchestrationStore(path)
    leftover = _create_atomic_temp_file(path, "private leftover")
    original_unlink = Path.unlink

    def fail_owned_unlink(path: Path, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        if path == leftover:
            raise PermissionError("owned temp deletion denied")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_owned_unlink)

    with pytest.raises(PermissionError, match="owned temp deletion denied"):
        await store.clear_all()

    assert leftover.exists()


async def test_clear_all_does_not_remove_other_owner_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "task_orchestrations.json"
    store = OrchestrationStore(path)
    owned = _create_atomic_temp_file(path, "private owned content")
    other_owner = _create_atomic_temp_file(
        tmp_path / "task_orchestrations.json.atomic-other-owner",
        "other owner content",
    )

    await store.clear_all()

    assert not owned.exists()
    assert other_owner.read_text(encoding="utf-8") == "other owner content"


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
