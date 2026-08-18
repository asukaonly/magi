"""Pollable, secret-free operation records for memory portability work."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import errno
import os
from pathlib import Path
import stat
import threading
from typing import Annotated, Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from ...core.logger import get_logger
from ...utils.runtime import RuntimePaths
from .errors import MemoryPortabilityError

_MAX_OPERATION_FILES = 50
_MAX_OPERATION_FILE_BYTES = 128 * 1024
logger = get_logger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class MemoryPortabilityOperation(BaseModel):
    """User-facing snapshot of one memory portability job."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str
    kind: Literal["backup", "export", "inspect", "restore"]
    status: Literal["pending", "running", "succeeded", "failed"] = "pending"
    phase: str = "queued"
    progress_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    record_counts: dict[str, int] = Field(default_factory=dict)
    output_path: str | None = None
    file_size_bytes: int | None = Field(default=None, ge=0)
    created_at: str
    completed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    rollback_performed: bool = False
    safety_backup_path: str | None = None
    index_rebuild_status: str | None = None
    inspection: "MemoryRestoreInspection | None" = None


class PasswordRequiredMemoryRestoreInspection(BaseModel):
    """Secret-free result for an encrypted package awaiting a password."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["password_required"]
    encrypted: Literal[True]


class ReadyMemoryRestoreInspection(BaseModel):
    """Validated metadata for one private restore candidate."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["ready"]
    candidate_id: str
    encrypted: bool
    format_version: int = Field(ge=1)
    magi_version: str
    created_at: str
    scope: list[str]
    record_counts: dict[str, int]
    compatibility: Literal["compatible", "upgrade_required", "unsupported"]
    warnings: list[str]
    expires_at: str
    source_fingerprint: str


MemoryRestoreInspection = Annotated[
    PasswordRequiredMemoryRestoreInspection | ReadyMemoryRestoreInspection,
    Field(discriminator="state"),
]
_INSPECTION_ADAPTER = TypeAdapter(MemoryRestoreInspection)
MemoryPortabilityOperation.model_rebuild()


class _PersistedOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_pid: int
    operation: MemoryPortabilityOperation


OperationRunner = Callable[[str], Awaitable[None]]


class MemoryPortabilityOperationStore:
    """Admit one operation and persist sanitized progress across restarts."""

    def __init__(self, *, runtime_paths: RuntimePaths) -> None:
        self._runtime_paths = runtime_paths
        self._operations: dict[str, MemoryPortabilityOperation] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._state_lock = threading.RLock()
        self._admission_lock = asyncio.Lock()
        self._inspection_active = False
        self._active_restore_candidate_id: str | None = None
        self._loaded = False

    @property
    def operations_dir(self) -> Path:
        return self._runtime_paths.memory_portability_dir / "operations"

    async def start(
        self,
        *,
        kind: Literal["backup", "export", "inspect", "restore"],
        runner: OperationRunner,
        restore_candidate_id: str | None = None,
    ) -> MemoryPortabilityOperation:
        """Create and schedule one mutually exclusive background operation."""

        async with self._admission_lock:
            self._ensure_loaded()
            self._reject_if_busy()
            operation = MemoryPortabilityOperation(
                operation_id=str(uuid.uuid4()),
                kind=kind,
                created_at=_utc_now(),
            )
            with self._state_lock:
                self._persist_locked(operation)
                self._operations[operation.operation_id] = operation
                self._active_restore_candidate_id = (
                    restore_candidate_id if kind == "restore" else None
                )
            try:
                task = asyncio.create_task(
                    self._run_safely(operation.operation_id, runner),
                    name=f"memory-portability-{kind}-{operation.operation_id}",
                )
            except BaseException:
                with self._state_lock:
                    self._operations.pop(operation.operation_id, None)
                    self._active_restore_candidate_id = None
                    try:
                        (self.operations_dir / f"{operation.operation_id}.json").unlink()
                        _fsync_directory(self.operations_dir)
                    except OSError:
                        logger.warning(
                            "Failed to clean an unscheduled memory portability operation",
                            operation_id=operation.operation_id,
                            exc_info=True,
                        )
                raise
            with self._state_lock:
                self._tasks[operation.operation_id] = task
            task.add_done_callback(
                lambda _task, operation_id=operation.operation_id: self._forget_task(operation_id)
            )
            return operation.model_copy(deep=True)

    @asynccontextmanager
    async def maintenance_boundary(self):
        """Reserve portability while full user-content clear removes private state."""

        async with self._admission_lock:
            self._ensure_loaded()
            self._reject_if_busy()
            self._inspection_active = True
        try:
            yield
        finally:
            async with self._admission_lock:
                self._inspection_active = False

    def reset_after_private_clear(self) -> None:
        """Forget cached completed records after their private files are cleared."""

        with self._state_lock:
            active_tasks = [task for task in self._tasks.values() if not task.done()]
            if self._active_locked() is not None or active_tasks:
                raise RuntimeError("Memory portability state is still active")
            self._operations.clear()
            self._tasks.clear()
            self._active_restore_candidate_id = None
            self._loaded = True

    async def ensure_candidate_can_be_deleted(self, candidate_id: str) -> None:
        """Reject deletion while a restore job owns the candidate."""

        async with self._admission_lock:
            self._ensure_loaded()
            if self._active_restore_candidate_id == str(candidate_id):
                active = self._active_locked()
                if active is not None:
                    raise MemoryPortabilityError(
                        "candidate_in_use",
                        "The restore candidate is being used by an active operation.",
                        status_code=409,
                    )

    def get(self, operation_id: str) -> MemoryPortabilityOperation | None:
        """Return one immutable operation snapshot."""

        self._ensure_loaded()
        try:
            normalized = str(uuid.UUID(str(operation_id)))
        except ValueError:
            return None
        if normalized != str(operation_id):
            return None
        with self._state_lock:
            operation = self._operations.get(normalized)
            return operation.model_copy(deep=True) if operation is not None else None

    def active(self) -> MemoryPortabilityOperation | None:
        """Return the one active operation, if present."""

        self._ensure_loaded()
        with self._state_lock:
            operation = self._active_locked()
            return operation.model_copy(deep=True) if operation is not None else None

    def latest(self) -> MemoryPortabilityOperation | None:
        """Return the newest retained operation, including terminal operations."""

        self._ensure_loaded()
        with self._state_lock:
            if not self._operations:
                return None
            operation = max(
                self._operations.values(),
                key=lambda item: (item.created_at, item.operation_id),
            )
            return operation.model_copy(deep=True)

    def resolve_restore_after_startup(
        self,
        operation_id: str,
        *,
        outcome: str,
        safety_backup_path: str | None,
    ) -> None:
        """Reconcile a restore job with the durable startup-recovery outcome."""

        if outcome not in {"aborted", "committed", "rolled_back"}:
            raise ValueError("Invalid startup restore outcome")
        self._ensure_loaded()
        with self._state_lock:
            operation = self._operations.get(str(operation_id))
            if operation is None or operation.kind != "restore":
                return
            if operation.status == "succeeded" and outcome != "committed":
                return
            updated = operation.model_copy(deep=True)
            updated.completed_at = _utc_now()
            updated.safety_backup_path = safety_backup_path
            if outcome == "committed":
                updated.status = "succeeded"
                updated.phase = "completed"
                updated.progress_percent = 100.0
                updated.error_code = None
                updated.error_message = None
                updated.rollback_performed = False
                updated.index_rebuild_status = updated.index_rebuild_status or "pending"
            else:
                updated.status = "failed"
                updated.phase = "failed"
                updated.error_code = "operation_interrupted"
                updated.error_message = (
                    "The interrupted memory restore was rolled back safely."
                    if outcome == "rolled_back"
                    else "The interrupted memory restore stopped before replacement began."
                )
                updated.rollback_performed = outcome == "rolled_back"
            try:
                self._persist_locked(updated)
            except MemoryPortabilityError:
                logger.warning(
                    "Recovered memory restore status is available only in memory",
                    operation_id=operation_id,
                    outcome=outcome,
                    exc_info=True,
                )
            self._operations[operation.operation_id] = updated
            self._prune_locked()

    def update(
        self,
        operation_id: str,
        *,
        phase: str,
        progress_percent: float,
        record_counts: dict[str, int] | None = None,
        safety_backup_path: str | None = None,
        index_rebuild_status: str | None = None,
    ) -> None:
        """Persist one safe progress transition."""

        with self._state_lock:
            operation = self._require_locked(operation_id)
            if operation.status in {"succeeded", "failed"}:
                return
            updated = operation.model_copy(deep=True)
            updated.status = "running"
            updated.phase = _safe_phase(phase)
            updated.progress_percent = max(0.0, min(float(progress_percent), 99.0))
            if record_counts is not None:
                updated.record_counts = {
                    str(key): max(int(value), 0) for key, value in record_counts.items()
                }
            if safety_backup_path is not None:
                updated.safety_backup_path = str(safety_backup_path)
            if index_rebuild_status is not None:
                updated.index_rebuild_status = _safe_phase(index_rebuild_status)
            self._persist_locked(updated)
            self._operations[operation.operation_id] = updated

    def succeed(
        self,
        operation_id: str,
        *,
        output_path: str | None = None,
        file_size_bytes: int | None = None,
        record_counts: dict[str, int] | None = None,
        safety_backup_path: str | None = None,
        index_rebuild_status: str | None = None,
        inspection: MemoryRestoreInspection | dict[str, Any] | None = None,
    ) -> None:
        """Persist successful completion."""

        with self._state_lock:
            operation = self._require_locked(operation_id)
            if operation.status in {"succeeded", "failed"}:
                return
            updated = operation.model_copy(deep=True)
            updated.status = "succeeded"
            updated.phase = "completed"
            updated.progress_percent = 100.0
            updated.completed_at = _utc_now()
            updated.output_path = str(output_path) if output_path is not None else None
            updated.file_size_bytes = (
                max(int(file_size_bytes), 0) if file_size_bytes is not None else None
            )
            if record_counts is not None:
                updated.record_counts = {
                    str(key): max(int(value), 0) for key, value in record_counts.items()
                }
            if safety_backup_path is not None:
                updated.safety_backup_path = str(safety_backup_path)
            if index_rebuild_status is not None:
                updated.index_rebuild_status = _safe_phase(index_rebuild_status)
            if inspection is not None:
                updated.inspection = _INSPECTION_ADAPTER.validate_python(inspection)
            updated.error_code = None
            updated.error_message = None
            self._persist_locked(updated)
            self._operations[operation.operation_id] = updated
            self._prune_locked()

    def fail(
        self,
        operation_id: str,
        *,
        code: str,
        message: str,
        rollback_performed: bool = False,
        safety_backup_path: str | None = None,
    ) -> None:
        """Persist a fixed, secret-free failure."""

        with self._state_lock:
            operation = self._require_locked(operation_id)
            if operation.status in {"succeeded", "failed"}:
                return
            updated = operation.model_copy(deep=True)
            updated.status = "failed"
            updated.phase = "failed"
            updated.completed_at = _utc_now()
            updated.error_code = _safe_code(code)
            updated.error_message = _safe_message(message)
            updated.rollback_performed = bool(rollback_performed)
            if safety_backup_path is not None:
                updated.safety_backup_path = str(safety_backup_path)
            try:
                self._persist_locked(updated)
            except MemoryPortabilityError:
                logger.warning(
                    "Memory portability failure status is available only in memory",
                    operation_id=operation_id,
                    error_code=updated.error_code,
                    exc_info=True,
                )
            self._operations[operation.operation_id] = updated
            self._prune_locked()

    async def _run_safely(self, operation_id: str, runner: OperationRunner) -> None:
        try:
            await runner(operation_id)
        except MemoryPortabilityError as exc:
            self.fail(operation_id, code=exc.code, message=str(exc))
        except asyncio.CancelledError:
            self.fail(
                operation_id,
                code="operation_cancelled",
                message="The memory portability operation was cancelled.",
            )
            logger.info("Memory portability operation was cancelled", operation_id=operation_id)
        except Exception:
            logger.exception(
                "Memory portability operation failed unexpectedly",
                operation_id=operation_id,
            )
            self.fail(
                operation_id,
                code="operation_failed",
                message="The memory portability operation could not be completed.",
            )
        finally:
            async with self._admission_lock:
                with self._state_lock:
                    if self._active_restore_candidate_id is not None:
                        operation = self._operations.get(operation_id)
                        if operation is not None and operation.kind == "restore":
                            self._active_restore_candidate_id = None

    def _reject_if_busy(self) -> None:
        if self._inspection_active or self._active_locked() is not None:
            raise MemoryPortabilityError(
                "operation_in_progress",
                "Another memory data operation is already in progress.",
                status_code=409,
            )

    def _active_locked(self) -> MemoryPortabilityOperation | None:
        with self._state_lock:
            return next(
                (
                    operation
                    for operation in self._operations.values()
                    if operation.status in {"pending", "running"}
                ),
                None,
            )

    def _require_locked(self, operation_id: str) -> MemoryPortabilityOperation:
        operation = self._operations.get(str(operation_id))
        if operation is None:
            raise RuntimeError("Memory portability operation is not registered")
        return operation

    def _forget_task(self, operation_id: str) -> None:
        with self._state_lock:
            self._tasks.pop(operation_id, None)

    def _ensure_loaded(self) -> None:
        with self._state_lock:
            if self._loaded:
                return
            directory = self.operations_dir
            try:
                directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                if os.name != "nt":
                    directory.chmod(0o700)
                paths = sorted(directory.glob("*.json"))
            except OSError as exc:
                raise _operation_storage_error(exc) from exc
            for path in paths:
                operation = self._read_operation(path)
                if operation is not None:
                    self._operations[operation.operation_id] = operation
            self._loaded = True
            self._prune_locked()

    def _read_operation(self, path: Path) -> MemoryPortabilityOperation | None:
        try:
            details = path.lstat()
            if (
                not stat.S_ISREG(details.st_mode)
                or stat.S_ISLNK(details.st_mode)
                or details.st_size > _MAX_OPERATION_FILE_BYTES
            ):
                return None
            persisted = _PersistedOperation.model_validate_json(path.read_bytes())
            normalized = str(uuid.UUID(persisted.operation.operation_id))
            if normalized != persisted.operation.operation_id or path.name != f"{normalized}.json":
                return None
        except (OSError, ValueError, ValidationError):
            return None
        operation = persisted.operation
        if operation.status in {"pending", "running"}:
            updated = operation.model_copy(deep=True)
            updated.status = "failed"
            updated.phase = "failed"
            updated.completed_at = _utc_now()
            updated.error_code = "operation_interrupted"
            updated.error_message = "The operation was interrupted before it completed."
            try:
                self._persist_locked(updated)
            except MemoryPortabilityError:
                logger.warning(
                    "Interrupted memory portability status is available only in memory",
                    operation_id=operation.operation_id,
                    exc_info=True,
                )
            operation = updated
        return operation

    def _persist_locked(self, operation: MemoryPortabilityOperation) -> None:
        directory = self.operations_dir
        temporary: Path | None = None
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            target = directory / f"{operation.operation_id}.json"
            payload = _PersistedOperation(
                owner_pid=os.getpid(),
                operation=operation,
            ).model_dump_json()
            temporary = directory / f".{operation.operation_id}.{uuid.uuid4().hex}.partial"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(temporary, flags, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            _fsync_directory(directory)
        except OSError as exc:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            raise _operation_storage_error(exc) from exc

    def _prune_locked(self) -> None:
        finished = sorted(
            (
                operation
                for operation in self._operations.values()
                if operation.status in {"succeeded", "failed"}
            ),
            key=lambda operation: operation.completed_at or operation.created_at,
            reverse=True,
        )
        for operation in finished[_MAX_OPERATION_FILES:]:
            try:
                (self.operations_dir / f"{operation.operation_id}.json").unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Failed to prune a memory portability operation",
                    operation_id=operation.operation_id,
                    exc_info=True,
                )
                continue
            self._operations.pop(operation.operation_id, None)


def _safe_code(value: str) -> str:
    normalized = str(value or "operation_failed")
    if not normalized.replace("_", "").isalnum() or len(normalized) > 100:
        return "operation_failed"
    return normalized


def _operation_storage_error(exc: OSError) -> MemoryPortabilityError:
    if exc.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)}:
        return MemoryPortabilityError(
            "insufficient_space",
            "There is not enough free space to record the memory data operation.",
            status_code=507,
        )
    return MemoryPortabilityError(
        "operation_state_write_failed",
        "The memory data operation status could not be saved safely.",
        status_code=500,
    )


def _safe_phase(value: str) -> str:
    normalized = str(value or "running")
    if not normalized.replace("_", "").isalnum() or len(normalized) > 100:
        return "running"
    return normalized


def _safe_message(value: str) -> str:
    normalized = str(value or "The memory portability operation failed.")
    return normalized[:500]


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "MemoryPortabilityOperation",
    "MemoryPortabilityOperationStore",
    "MemoryRestoreInspection",
    "PasswordRequiredMemoryRestoreInspection",
    "ReadyMemoryRestoreInspection",
]
