from __future__ import annotations

import asyncio
import errno
import json
import os
from pathlib import Path

import pytest

from magi.memory.portability import operations as operations_module
from magi.memory.portability.errors import MemoryPortabilityError
from magi.memory.portability.operations import MemoryPortabilityOperationStore
from magi.utils.runtime import RuntimePaths


@pytest.mark.asyncio
async def test_operation_store_serializes_jobs_and_persists_completion(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    store = MemoryPortabilityOperationStore(runtime_paths=paths)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def runner(operation_id: str) -> None:
        store.update(operation_id, phase="snapshotting", progress_percent=10)
        entered.set()
        await release.wait()
        store.succeed(
            operation_id,
            output_path="/private/backup.magibackup",
            file_size_bytes=123,
            record_counts={"l1_events": 2},
        )

    operation = await store.start(kind="backup", runner=runner)
    await entered.wait()

    with pytest.raises(MemoryPortabilityError) as conflict:
        await store.start(kind="export", runner=runner)
    assert conflict.value.code == "operation_in_progress"

    release.set()
    for _ in range(20):
        completed = store.get(operation.operation_id)
        if completed is not None and completed.status == "succeeded":
            break
        await asyncio.sleep(0.01)

    assert completed is not None
    assert completed.status == "succeeded"
    assert completed.progress_percent == 100
    assert completed.record_counts == {"l1_events": 2}
    assert completed.output_path == "/private/backup.magibackup"

    reloaded = MemoryPortabilityOperationStore(runtime_paths=paths).get(operation.operation_id)
    assert reloaded == completed
    persisted = store.operations_dir / f"{operation.operation_id}.json"
    if os.name != "nt":
        assert persisted.stat().st_mode & 0o777 == 0o600
        assert store.operations_dir.stat().st_mode & 0o777 == 0o700


@pytest.mark.asyncio
async def test_inspection_is_pollable_and_blocks_other_jobs(tmp_path: Path) -> None:
    store = MemoryPortabilityOperationStore(runtime_paths=RuntimePaths(tmp_path / "runtime"))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def inspect_runner(operation_id: str) -> None:
        entered.set()
        await release.wait()
        store.succeed(
            operation_id,
            inspection={"state": "password_required", "encrypted": True},
        )

    inspection = await store.start(kind="inspect", runner=inspect_runner)
    await entered.wait()

    async def no_op(_operation_id: str) -> None:
        return None

    with pytest.raises(MemoryPortabilityError) as conflict:
        await store.start(kind="backup", runner=no_op)
    assert conflict.value.code == "operation_in_progress"

    release.set()
    for _ in range(20):
        completed = store.get(inspection.operation_id)
        if completed is not None and completed.status == "succeeded":
            break
        await asyncio.sleep(0.01)
    assert completed is not None
    assert completed.inspection is not None
    assert completed.inspection.state == "password_required"
    assert store.latest() == completed


@pytest.mark.asyncio
async def test_maintenance_boundary_blocks_jobs_and_can_reset_completed_records(
    tmp_path: Path,
) -> None:
    store = MemoryPortabilityOperationStore(runtime_paths=RuntimePaths(tmp_path / "runtime"))
    boundary_entered = asyncio.Event()
    release = asyncio.Event()

    async def hold_boundary() -> None:
        async with store.maintenance_boundary():
            boundary_entered.set()
            await release.wait()

    boundary_task = asyncio.create_task(hold_boundary())
    await boundary_entered.wait()

    async def no_op(_operation_id: str) -> None:
        return None

    with pytest.raises(MemoryPortabilityError) as conflict:
        await store.start(kind="backup", runner=no_op)
    assert conflict.value.code == "operation_in_progress"

    store.reset_after_private_clear()
    release.set()
    await boundary_task
    assert store.active() is None


def test_stale_running_operation_is_failed_on_new_process_load(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    operation_id = "1f70a520-9145-43a5-91db-bc95a210154e"
    operations_dir = paths.memory_portability_dir / "operations"
    operations_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    (operations_dir / f"{operation_id}.json").write_text(
        json.dumps(
            {
                "owner_pid": 999999,
                "operation": {
                    "operation_id": operation_id,
                    "kind": "restore",
                    "status": "running",
                    "phase": "cutover",
                    "progress_percent": 55,
                    "record_counts": {},
                    "output_path": None,
                    "file_size_bytes": None,
                    "created_at": "2026-08-18T00:00:00Z",
                    "completed_at": None,
                    "error_code": None,
                    "error_message": None,
                    "rollback_performed": False,
                    "safety_backup_path": None,
                    "index_rebuild_status": None,
                },
            }
        ),
        encoding="utf-8",
    )

    operation = MemoryPortabilityOperationStore(runtime_paths=paths).get(operation_id)

    assert operation is not None
    assert operation.status == "failed"
    assert operation.error_code == "operation_interrupted"
    assert operation.completed_at is not None


@pytest.mark.asyncio
async def test_operation_admission_rolls_back_when_initial_state_cannot_be_saved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryPortabilityOperationStore(runtime_paths=RuntimePaths(tmp_path / "runtime"))
    assert store.latest() is None

    def no_space(*_args: object, **_kwargs: object) -> int:
        raise OSError(errno.ENOSPC, "disk full")

    monkeypatch.setattr(operations_module.os, "open", no_space)

    async def no_op(_operation_id: str) -> None:
        return None

    with pytest.raises(MemoryPortabilityError) as failure:
        await store.start(kind="backup", runner=no_op)

    assert failure.value.code == "insufficient_space"
    assert failure.value.status_code == 507
    assert store.active() is None


@pytest.mark.asyncio
async def test_failed_progress_write_keeps_previous_state_and_releases_busy_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryPortabilityOperationStore(runtime_paths=RuntimePaths(tmp_path / "runtime"))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def runner(_operation_id: str) -> None:
        entered.set()
        await release.wait()

    operation = await store.start(kind="backup", runner=runner)
    await entered.wait()

    def fail_persist(_operation: object) -> None:
        raise MemoryPortabilityError(
            "insufficient_space",
            "There is not enough free space to save progress.",
            status_code=507,
        )

    monkeypatch.setattr(store, "_persist_locked", fail_persist)

    with pytest.raises(MemoryPortabilityError):
        store.update(operation.operation_id, phase="snapshotting", progress_percent=10)
    unchanged = store.get(operation.operation_id)
    assert unchanged is not None
    assert unchanged.status == "pending"
    assert unchanged.phase == "queued"

    store.fail(
        operation.operation_id,
        code="insufficient_space",
        message="There is not enough free space.",
    )
    failed = store.get(operation.operation_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "insufficient_space"
    assert store.active() is None

    release.set()
    await asyncio.sleep(0)
