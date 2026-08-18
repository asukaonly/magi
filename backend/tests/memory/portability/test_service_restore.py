from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from magi.memory.portability import restore as restore_module
from magi.memory.portability import service as service_module
from magi.memory.portability.errors import (
    BackupPasswordRequiredError,
    MemoryPortabilityError,
)
from magi.memory.portability.operations import MemoryPortabilityOperation
from magi.memory.portability.service import MemoryPortabilityService
from magi.utils.runtime import RuntimePaths


class _OperationRecorder:
    def __init__(self, events: list[str], *, fail_succeed: bool = False) -> None:
        self.events = events
        self.fail_succeed = fail_succeed
        self.failed: dict[str, object] | None = None
        self.succeeded: dict[str, object] | None = None

    def update(self, _operation_id: str, *, phase: str, **_values: object) -> None:
        self.events.append(f"phase:{phase}")

    def succeed(self, _operation_id: str, **values: object) -> None:
        self.events.append("succeed")
        if self.fail_succeed:
            raise MemoryPortabilityError(
                "insufficient_space",
                "The operation status could not be persisted.",
                status_code=507,
            )
        self.succeeded = values

    def fail(self, _operation_id: str, **values: object) -> None:
        self.events.append("fail")
        self.failed = values

    def resolve_restore_after_startup(
        self,
        _operation_id: str,
        *,
        outcome: str,
        **values: object,
    ) -> None:
        self.events.append(f"resolve:{outcome}")
        self.succeeded = values


class _Memory:
    def __init__(self, events: list[str], archive_dir: Path) -> None:
        self.events = events
        self._archive_dir = archive_dir

    @asynccontextmanager
    async def memory_runtime_replacement_guard(self):
        self.events.append("guard.enter")
        try:
            yield
        finally:
            self.events.append("guard.exit")


class _RebuildManager:
    def __init__(self, events: list[str], *, fail_start: bool = False) -> None:
        self.events = events
        self.fail_start = fail_start

    async def pause_starts_and_cancel_all(self) -> int:
        self.events.append("rebuild.pause")
        return 0

    async def resume_starts(self) -> None:
        self.events.append("rebuild.resume")

    async def resume_and_start_rebuild(self, **_values: object) -> dict[str, object]:
        self.events.append("rebuild.start")
        if self.fail_start:
            raise RuntimeError("rebuild queue unavailable")
        return {"status": "pending", "job_id": "embedding-rebuild-test"}


class _Transaction:
    def __init__(
        self,
        events: list[str],
        safety_backup_path: Path,
        *,
        fail_finalize: bool = False,
        fail_commit_after_durable: bool = False,
        commit_started: threading.Event | None = None,
        release_commit: threading.Event | None = None,
    ) -> None:
        self.events = events
        self.safety_backup_path = safety_backup_path
        self.fail_finalize = fail_finalize
        self.fail_commit_after_durable = fail_commit_after_durable
        self.commit_started = commit_started
        self.release_commit = release_commit
        self.commit_is_durable = False

    @contextmanager
    def activation_guard(self):
        self.events.append("activation.enter")
        try:
            yield
        finally:
            self.events.append("activation.exit")

    def cutover(self) -> None:
        self.events.append("cutover")

    def rollback(self) -> None:
        self.events.append("rollback")

    def close(self) -> None:
        self.events.append("close")

    def commit(self) -> None:
        self.events.append("commit")
        if self.commit_started is not None:
            self.commit_started.set()
        if self.release_commit is not None:
            assert self.release_commit.wait(timeout=5)
        self.commit_is_durable = True
        if self.fail_commit_after_durable:
            raise OSError("journal directory sync failed")

    def has_installed_commit(self) -> bool:
        self.events.append("verify.commit")
        return self.commit_is_durable

    def finalize_commit(self) -> None:
        self.events.append("finalize")
        if self.fail_finalize:
            raise OSError("committed cleanup blocked")


async def _wait_for_operation(
    service: MemoryPortabilityService,
    operation_id: str,
) -> MemoryPortabilityOperation:
    for _ in range(100):
        operation = service.get_operation(operation_id)
        if operation is not None and operation.status in {"succeeded", "failed"}:
            return operation
        await asyncio.sleep(0.01)
    raise AssertionError("operation did not complete")


@pytest.mark.asyncio
async def test_restore_inspection_is_pollable_without_persisting_password(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    service = MemoryPortabilityService(runtime_paths=paths)
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)
    secret = "inspection-secret-dfcf47"

    async def capture_archive_target() -> Path:
        return archive_target

    def inspect(**values: object) -> object:
        assert values["password"] == secret
        raise BackupPasswordRequiredError()

    monkeypatch.setattr(service, "_capture_archive_target", capture_archive_target)
    monkeypatch.setattr(service_module, "inspect_memory_backup", inspect)

    started = await service.start_inspection(
        source_path=tmp_path / "memory.magibackup",
        password=secret,
    )
    completed = await _wait_for_operation(service, started.operation_id)

    assert completed.status == "succeeded"
    assert completed.kind == "inspect"
    assert completed.inspection is not None
    assert completed.inspection.state == "password_required"
    persisted = service.operations.operations_dir / f"{started.operation_id}.json"
    assert secret.encode("utf-8") not in persisted.read_bytes()


def _wire_restore(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    fail_initialize_once: bool = False,
    fail_rebuild_start: bool = False,
    fail_candidate_delete: bool = False,
    fail_operation_success: bool = False,
    fail_finalize: bool = False,
    fail_commit_after_durable: bool = False,
    commit_started: threading.Event | None = None,
    release_commit: threading.Event | None = None,
) -> tuple[MemoryPortabilityService, _OperationRecorder, list[str]]:
    from magi.bootstrap import backend as backend_module
    from magi.memory.embedding import vector_admin

    events: list[str] = []
    paths = RuntimePaths(tmp_path / "runtime")
    service = MemoryPortabilityService(runtime_paths=paths)
    operations = _OperationRecorder(events, fail_succeed=fail_operation_success)
    service.operations = operations  # type: ignore[assignment]
    replacement_memory = object()
    transaction = _Transaction(
        events,
        paths.memory_backups_dir / "safety.magibackup",
        fail_finalize=fail_finalize,
        fail_commit_after_durable=fail_commit_after_durable,
        commit_started=commit_started,
        release_commit=release_commit,
    )
    manager = _RebuildManager(events, fail_start=fail_rebuild_start)
    initialize_calls = 0
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)
    old_memory = _Memory(events, archive_target)

    async def shutdown_runtime(*, strict: bool = False) -> None:
        assert strict is True
        events.append("runtime.shutdown")

    async def initialize_runtime() -> None:
        nonlocal initialize_calls
        initialize_calls += 1
        events.append("runtime.initialize")
        if fail_initialize_once and initialize_calls == 1:
            raise RuntimeError("replacement startup failed")

    async def prepare_restore(**_values: object) -> _Transaction:
        events.append("prepare")
        return transaction

    class _CandidateAdapter:
        @staticmethod
        def from_preflight(**_values: object) -> object:
            events.append("candidate")
            return object()

    manifest = SimpleNamespace(counts={"l1_events": 2, "l2_entities": 1})
    monkeypatch.setattr(
        service_module,
        "load_restore_candidate",
        lambda **_values: (
            tmp_path / "candidate",
            {"archive_target": str(archive_target)},
            manifest,
        ),
    )

    def delete_candidate(**_values: object) -> None:
        events.append("delete")
        if fail_candidate_delete:
            raise PermissionError("candidate cleanup blocked")

    monkeypatch.setattr(service_module, "delete_restore_candidate", delete_candidate)
    monkeypatch.setattr(service, "_optional_unified_memory", lambda: old_memory)
    monkeypatch.setattr(service, "_archive_directory", lambda: archive_target)
    monkeypatch.setattr(service_module, "get_unified_memory", lambda: replacement_memory)
    monkeypatch.setattr(restore_module, "ValidatedRestoreCandidate", _CandidateAdapter)
    monkeypatch.setattr(restore_module, "prepare_memory_restore", prepare_restore)
    monkeypatch.setattr(vector_admin, "get_embedding_rebuild_manager", lambda: manager)
    monkeypatch.setattr(backend_module, "shutdown_agent_runtime", shutdown_runtime)
    monkeypatch.setattr(backend_module, "initialize_agent_runtime", initialize_runtime)
    return service, operations, events


@pytest.mark.asyncio
async def test_restore_commits_only_after_runtime_restart_and_rebuild_queue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, operations, events = _wire_restore(monkeypatch, tmp_path)

    await service._run_restore(operation_id="restore-op", candidate_id="candidate-id")

    assert operations.failed is None
    assert operations.succeeded is not None
    assert operations.succeeded["index_rebuild_status"] == "pending"
    assert events.index("runtime.initialize") < events.index("rebuild.start")
    assert events.index("rebuild.start") < events.index("commit")
    assert events.index("commit") < events.index("succeed")
    assert events.index("succeed") < events.index("finalize") < events.index("delete")
    assert events[-1] == "guard.exit"


@pytest.mark.asyncio
async def test_restore_remains_succeeded_when_candidate_cleanup_is_deferred(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, operations, events = _wire_restore(
        monkeypatch,
        tmp_path,
        fail_candidate_delete=True,
    )

    await service._run_restore(operation_id="restore-op", candidate_id="candidate-id")

    assert operations.failed is None
    assert operations.succeeded is not None
    assert (
        events.index("commit")
        < events.index("succeed")
        < events.index("finalize")
        < events.index("delete")
    )
    assert events[-1] == "guard.exit"


@pytest.mark.asyncio
async def test_restore_remains_succeeded_when_committed_cleanup_is_deferred(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, operations, events = _wire_restore(
        monkeypatch,
        tmp_path,
        fail_finalize=True,
    )

    await service._run_restore(operation_id="restore-op", candidate_id="candidate-id")

    assert operations.failed is None
    assert operations.succeeded is not None
    assert events.index("commit") < events.index("succeed") < events.index("finalize")
    assert events.index("finalize") < events.index("delete")
    assert events[-1] == "guard.exit"


@pytest.mark.asyncio
async def test_durable_commit_survives_operation_success_write_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, operations, events = _wire_restore(
        monkeypatch,
        tmp_path,
        fail_operation_success=True,
    )

    await service._run_restore(operation_id="restore-op", candidate_id="candidate-id")

    assert operations.failed is None
    assert operations.succeeded is not None
    assert events.index("commit") < events.index("succeed")
    assert "resolve:committed" in events
    assert "finalize" not in events
    assert "delete" not in events
    assert events[-1] == "guard.exit"


@pytest.mark.asyncio
async def test_restore_accepts_installed_commit_when_directory_sync_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, operations, events = _wire_restore(
        monkeypatch,
        tmp_path,
        fail_commit_after_durable=True,
    )

    await service._run_restore(operation_id="restore-op", candidate_id="candidate-id")

    assert operations.failed is None
    assert operations.succeeded is not None
    assert events.index("commit") < events.index("verify.commit") < events.index("succeed")
    assert "rollback" not in events


@pytest.mark.asyncio
async def test_restore_defers_cancellation_until_durable_commit_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commit_started = threading.Event()
    release_commit = threading.Event()
    service, operations, events = _wire_restore(
        monkeypatch,
        tmp_path,
        commit_started=commit_started,
        release_commit=release_commit,
    )

    restoring = asyncio.create_task(
        service._run_restore(operation_id="restore-op", candidate_id="candidate-id")
    )
    assert await asyncio.to_thread(commit_started.wait, 2)
    restoring.cancel()
    release_commit.set()
    await restoring

    assert operations.failed is None
    assert operations.succeeded is not None
    assert events.index("commit") < events.index("succeed")
    assert "rollback" not in events


@pytest.mark.asyncio
async def test_restore_rolls_back_when_replacement_runtime_fails_to_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, operations, events = _wire_restore(
        monkeypatch,
        tmp_path,
        fail_initialize_once=True,
    )

    await service._run_restore(operation_id="restore-op", candidate_id="candidate-id")

    assert operations.succeeded is None
    assert operations.failed is not None
    assert operations.failed["rollback_performed"] is True
    assert operations.failed["code"] == "restore_runtime_start_failed"
    assert events.count("runtime.initialize") == 2
    assert events.index("rollback") < events.index("fail")
    assert events[-2:] == ["guard.exit", "rebuild.resume"]


@pytest.mark.asyncio
async def test_restore_keeps_rebuilds_paused_while_rolling_back_queue_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, operations, events = _wire_restore(
        monkeypatch,
        tmp_path,
        fail_rebuild_start=True,
    )

    await service._run_restore(operation_id="restore-op", candidate_id="candidate-id")

    assert operations.succeeded is None
    assert operations.failed is not None
    assert operations.failed["rollback_performed"] is True
    assert operations.failed["code"] == "index_rebuild_queue_failed"
    assert events.count("rebuild.pause") == 1
    assert events.index("rollback") < events.index("fail")
    assert events.index("rollback") < events.index("rebuild.resume")
    assert events[-1] == "rebuild.resume"


@pytest.mark.asyncio
async def test_restore_rejects_archive_config_that_differs_from_live_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, operations, events = _wire_restore(monkeypatch, tmp_path)
    configured_target = tmp_path / "configured-archive"
    configured_target.mkdir()
    monkeypatch.setattr(service, "_archive_directory", lambda: configured_target)

    await service._run_restore(operation_id="restore-op", candidate_id="candidate-id")

    assert operations.succeeded is None
    assert operations.failed is not None
    assert operations.failed["code"] == "archive_runtime_stale"
    assert "runtime.shutdown" not in events


@pytest.mark.asyncio
async def test_snapshot_rejects_archive_config_that_differs_from_live_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    service = MemoryPortabilityService(runtime_paths=paths)
    live_target = tmp_path / "live-archive"
    configured_target = tmp_path / "configured-archive"
    live_target.mkdir()
    configured_target.mkdir()
    memory = _Memory([], live_target)
    snapshot = pytest.fail

    monkeypatch.setattr(service, "_optional_unified_memory", lambda: memory)
    monkeypatch.setattr(service, "_archive_directory", lambda: configured_target)
    monkeypatch.setattr(service_module, "create_memory_snapshot", snapshot)

    with pytest.raises(MemoryPortabilityError) as failure:
        await service._create_consistent_snapshot(include_l0=True)

    assert failure.value.code == "archive_runtime_stale"


@pytest.mark.asyncio
async def test_full_clear_boundary_rejects_stale_live_archive_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    service = MemoryPortabilityService(runtime_paths=paths)
    live_target = tmp_path / "live-archive"
    configured_target = tmp_path / "configured-archive"
    live_target.mkdir()
    configured_target.mkdir()

    monkeypatch.setattr(
        service,
        "_optional_unified_memory",
        lambda: _Memory([], live_target),
    )
    monkeypatch.setattr(service, "_archive_directory", lambda: configured_target)

    with pytest.raises(MemoryPortabilityError) as failure:
        async with service.user_content_clear_boundary():
            pytest.fail("stale archive configuration must not enter full clear")

    assert failure.value.code == "archive_runtime_stale"


@pytest.mark.asyncio
async def test_full_clear_boundary_holds_configuration_updates_until_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    service = MemoryPortabilityService(runtime_paths=paths)
    config_lock = asyncio.Lock()
    update_acquired = asyncio.Event()

    monkeypatch.setattr(
        service_module,
        "get_embedding_config_update_lock",
        lambda: config_lock,
    )
    monkeypatch.setattr(
        service,
        "_archive_directory_for_live_runtime",
        lambda _memory: paths.memory_dir,
    )

    async def update_configuration() -> None:
        async with config_lock:
            update_acquired.set()

    async with service.user_content_clear_boundary():
        update = asyncio.create_task(update_configuration())
        await asyncio.sleep(0)
        assert update_acquired.is_set() is False

    await update
    assert update_acquired.is_set() is True


@pytest.mark.asyncio
async def test_full_clear_boundary_reports_unavailable_archive_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    service = MemoryPortabilityService(runtime_paths=paths)
    invalid_target = tmp_path / "archive-file"
    invalid_target.write_text("not a directory", encoding="utf-8")
    config = SimpleNamespace(
        agent=SimpleNamespace(
            memory=SimpleNamespace(archive_path=str(invalid_target)),
        )
    )

    monkeypatch.setattr(service_module, "get_config", lambda: config)
    monkeypatch.setattr(service, "_optional_unified_memory", lambda: None)

    with pytest.raises(MemoryPortabilityError) as failure:
        async with service.user_content_clear_boundary():
            pytest.fail("an unavailable archive target must reject full clear")

    assert failure.value.code == "archive_target_invalid"
    assert failure.value.status_code == 500
