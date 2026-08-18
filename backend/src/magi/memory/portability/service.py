"""Application service for backup, readable export, and restore operations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ...config import get_config
from ...config.embedding_coordination import get_embedding_config_update_lock
from ...core.logger import get_logger
from ...utils.runtime import RuntimePaths, get_runtime_paths
from ..provider import get_unified_memory
from .backup import _require_output_directory, build_memory_backup
from .errors import BackupPasswordRequiredError, MemoryPortabilityError
from .export import build_readable_export
from .models import BACKUP_FORMAT_VERSION, BackupInspection
from .operations import MemoryPortabilityOperation, MemoryPortabilityOperationStore
from .preflight import (
    delete_restore_candidate,
    inspect_memory_backup,
    load_restore_candidate,
)
from .storage import create_memory_snapshot, discard_snapshot

logger = get_logger(__name__)


@dataclass(slots=True)
class _RestoreRuntimeState:
    shutdown_attempted: bool = False
    runtime_offline: bool = False
    cutover_attempted: bool = False
    committed: bool = False
    commit_outcome_unknown: bool = False
    manager_paused: bool = False
    rollback_performed: bool = False
    transaction: Any | None = None
    safety_backup_path: str | None = None


class MemoryPortabilityService:
    """Coordinate mutually exclusive portability work outside request guards."""

    def __init__(self, *, runtime_paths: RuntimePaths) -> None:
        self.runtime_paths = runtime_paths
        self.operations = MemoryPortabilityOperationStore(runtime_paths=runtime_paths)

    async def start_backup(
        self,
        *,
        destination_directory: Path,
        encryption: Literal["password", "none"],
        password: str | None,
    ) -> MemoryPortabilityOperation:
        """Start one consistent restorable backup job."""

        destination = await asyncio.to_thread(
            _require_output_directory,
            Path(destination_directory),
        )

        async def runner(operation_id: str) -> None:
            await self._run_backup(
                operation_id=operation_id,
                destination_directory=destination,
                encryption=encryption,
                password=password,
            )

        return await self.operations.start(kind="backup", runner=runner)

    async def start_export(
        self,
        *,
        destination_directory: Path,
        include_l0: bool,
    ) -> MemoryPortabilityOperation:
        """Start one readable, explicitly non-restorable export job."""

        destination = await asyncio.to_thread(
            _require_output_directory,
            Path(destination_directory),
        )

        async def runner(operation_id: str) -> None:
            await self._run_export(
                operation_id=operation_id,
                destination_directory=destination,
                include_l0=include_l0,
            )

        return await self.operations.start(kind="export", runner=runner)

    async def start_inspection(
        self,
        *,
        source_path: Path,
        password: str | None,
    ) -> MemoryPortabilityOperation:
        """Start validation of an untrusted package as a pollable job."""

        async def runner(operation_id: str) -> None:
            await self._run_inspection(
                operation_id=operation_id,
                source_path=Path(source_path),
                password=password,
            )

        return await self.operations.start(kind="inspect", runner=runner)

    async def start_restore(self, *, candidate_id: str) -> MemoryPortabilityOperation:
        """Start replacement restore for one already inspected candidate."""

        async def runner(operation_id: str) -> None:
            await self._run_restore(
                operation_id=operation_id,
                candidate_id=str(candidate_id),
            )

        return await self.operations.start(
            kind="restore",
            runner=runner,
            restore_candidate_id=str(candidate_id),
        )

    async def delete_candidate(self, *, candidate_id: str) -> None:
        """Discard a candidate unless an active restore owns it."""

        await self.operations.ensure_candidate_can_be_deleted(str(candidate_id))
        await asyncio.to_thread(
            delete_restore_candidate,
            runtime_paths=self.runtime_paths,
            candidate_id=str(candidate_id),
        )

    def get_operation(self, operation_id: str) -> MemoryPortabilityOperation | None:
        return self.operations.get(operation_id)

    def get_active_operation(self) -> MemoryPortabilityOperation | None:
        return self.operations.active()

    def get_latest_operation(self) -> MemoryPortabilityOperation | None:
        return self.operations.latest()

    @asynccontextmanager
    async def user_content_clear_boundary(
        self,
    ) -> AsyncIterator[Callable[[], Awaitable[dict[str, int]]]]:
        """Block portability work and expose the private-state clearer."""

        from .recovery import clear_memory_portability_private_data

        async with self.operations.maintenance_boundary():
            async with get_embedding_config_update_lock():
                self._archive_directory_for_live_runtime(self._optional_unified_memory())

                async def clear_private_data() -> dict[str, int]:
                    counts = await asyncio.to_thread(
                        clear_memory_portability_private_data,
                        self.runtime_paths,
                    )
                    self.operations.reset_after_private_clear()
                    return counts

                yield clear_private_data

    async def _run_backup(
        self,
        *,
        operation_id: str,
        destination_directory: Path,
        encryption: Literal["password", "none"],
        password: str | None,
    ) -> None:
        snapshot = None
        try:
            self.operations.update(
                operation_id,
                phase="snapshotting",
                progress_percent=10,
            )
            snapshot = await self._create_consistent_snapshot(include_l0=True)
            self.operations.update(
                operation_id,
                phase="packaging",
                progress_percent=55,
                record_counts=dict(snapshot.counts),
            )
            output_path, manifest = await asyncio.to_thread(
                build_memory_backup,
                snapshot=snapshot,
                output_directory=destination_directory,
                encryption=encryption,
                password=password,
            )
            self.operations.succeed(
                operation_id,
                output_path=str(output_path),
                file_size_bytes=output_path.stat().st_size,
                record_counts=dict(manifest.counts),
            )
        finally:
            password = None
            if snapshot is not None:
                await asyncio.to_thread(discard_snapshot, snapshot)

    async def _run_export(
        self,
        *,
        operation_id: str,
        destination_directory: Path,
        include_l0: bool,
    ) -> None:
        snapshot = None
        try:
            self.operations.update(
                operation_id,
                phase="snapshotting",
                progress_percent=10,
            )
            snapshot = await self._create_consistent_snapshot(include_l0=include_l0)
            self.operations.update(
                operation_id,
                phase="exporting",
                progress_percent=55,
                record_counts=dict(snapshot.counts),
            )
            output_path, manifest = await asyncio.to_thread(
                build_readable_export,
                snapshot=snapshot,
                output_directory=destination_directory,
                include_l0=include_l0,
            )
            self.operations.succeed(
                operation_id,
                output_path=str(output_path),
                file_size_bytes=output_path.stat().st_size,
                record_counts={
                    str(key): int(value)
                    for key, value in dict(manifest.get("source_counts", {})).items()
                },
            )
        finally:
            if snapshot is not None:
                await asyncio.to_thread(discard_snapshot, snapshot)

    async def _run_inspection(
        self,
        *,
        operation_id: str,
        source_path: Path,
        password: str | None,
    ) -> None:
        """Validate one package and persist only a secret-free inspection result."""

        try:
            self.operations.update(
                operation_id,
                phase="validating",
                progress_percent=5,
            )
            archive_target = await self._capture_archive_target()
            try:
                inspection = await asyncio.to_thread(
                    inspect_memory_backup,
                    source_path=source_path,
                    password=password,
                    runtime_paths=self.runtime_paths,
                    archive_target=archive_target,
                )
            except BackupPasswordRequiredError:
                result: dict[str, Any] = {
                    "state": "password_required",
                    "encrypted": True,
                }
            else:
                result = _ready_inspection_payload(inspection)
            self.operations.succeed(operation_id, inspection=result)
        finally:
            password = None

    async def _run_restore(self, *, operation_id: str, candidate_id: str) -> None:
        """Replace memory only after a validated, rollback-capable cutover."""

        from ...bootstrap.backend import initialize_agent_runtime, shutdown_agent_runtime
        from ..embedding.vector_admin import VECTOR_LAYERS, get_embedding_rebuild_manager
        from .restore import ValidatedRestoreCandidate, prepare_memory_restore

        self.operations.update(operation_id, phase="validating", progress_percent=5)
        candidate_root, metadata, manifest = await asyncio.to_thread(
            load_restore_candidate,
            runtime_paths=self.runtime_paths,
            candidate_id=candidate_id,
        )
        candidate = ValidatedRestoreCandidate.from_preflight(
            candidate_root=candidate_root,
            metadata=metadata,
            manifest=manifest,
        )
        rebuild_manager = get_embedding_rebuild_manager()
        state = _RestoreRuntimeState()
        config_update_lock = get_embedding_config_update_lock()
        await config_update_lock.acquire()
        try:
            old_memory = self._optional_unified_memory()
            self._require_current_archive_target(metadata, old_memory)
            try:
                await rebuild_manager.pause_starts_and_cancel_all()
            except Exception as exc:
                raise MemoryPortabilityError(
                    "restore_runtime_busy",
                    "Active memory index work could not be stopped for restore.",
                    status_code=503,
                ) from exc
            state.manager_paused = True
            async with _runtime_replacement_boundary(old_memory):
                try:
                    await self._execute_restore_cutover(
                        operation_id=operation_id,
                        candidate_id=candidate_id,
                        candidate=candidate,
                        manifest=manifest,
                        state=state,
                        rebuild_manager=rebuild_manager,
                        vector_layers=VECTOR_LAYERS,
                        prepare_memory_restore=prepare_memory_restore,
                        initialize_agent_runtime=initialize_agent_runtime,
                        shutdown_agent_runtime=shutdown_agent_runtime,
                    )
                except BaseException as error:
                    if not isinstance(error, (Exception, asyncio.CancelledError)):
                        raise
                    await self._record_restore_failure(
                        operation_id=operation_id,
                        error=error,
                        state=state,
                        rebuild_manager=rebuild_manager,
                        initialize_agent_runtime=initialize_agent_runtime,
                        shutdown_agent_runtime=shutdown_agent_runtime,
                    )
        except BaseException as error:
            if not isinstance(error, (Exception, asyncio.CancelledError)):
                raise
            await self._record_restore_failure(
                operation_id=operation_id,
                error=error,
                state=state,
                rebuild_manager=rebuild_manager,
                initialize_agent_runtime=initialize_agent_runtime,
                shutdown_agent_runtime=shutdown_agent_runtime,
            )
        finally:
            try:
                if state.manager_paused:
                    await rebuild_manager.resume_starts()
            finally:
                config_update_lock.release()

    async def _execute_restore_cutover(
        self,
        *,
        operation_id: str,
        candidate_id: str,
        candidate: Any,
        manifest: Any,
        state: _RestoreRuntimeState,
        rebuild_manager: Any,
        vector_layers: Any,
        prepare_memory_restore: Any,
        initialize_agent_runtime: Any,
        shutdown_agent_runtime: Any,
    ) -> None:
        """Execute a restore while the previous runtime's exclusive guard is held."""

        self.operations.update(
            operation_id,
            phase="shutting_down",
            progress_percent=15,
            record_counts=dict(manifest.counts),
        )
        state.shutdown_attempted = True
        try:
            await shutdown_agent_runtime(strict=True)
        except Exception as exc:
            raise MemoryPortabilityError(
                "restore_runtime_shutdown_failed",
                "The current memory runtime could not be stopped safely.",
                status_code=500,
            ) from exc
        state.runtime_offline = True

        self.operations.update(
            operation_id,
            phase="safety_backup",
            progress_percent=25,
        )
        state.transaction = await prepare_memory_restore(
            candidate=candidate,
            runtime_paths=self.runtime_paths,
            operation_id=operation_id,
        )
        state.safety_backup_path = str(state.transaction.safety_backup_path)
        self.operations.update(
            operation_id,
            phase="cutover",
            progress_percent=50,
            safety_backup_path=state.safety_backup_path,
        )
        state.cutover_attempted = True
        await asyncio.to_thread(state.transaction.cutover)

        self.operations.update(
            operation_id,
            phase="restarting",
            progress_percent=75,
        )
        try:
            with state.transaction.activation_guard():
                await initialize_agent_runtime()
            replacement_memory = get_unified_memory()
        except Exception as exc:
            raise MemoryPortabilityError(
                "restore_runtime_start_failed",
                "The restored memory runtime did not start successfully.",
                status_code=500,
            ) from exc
        state.runtime_offline = False

        try:
            rebuild_job = await rebuild_manager.resume_and_start_rebuild(
                unified_memory=replacement_memory,
                layers=vector_layers,
            )
        except Exception as exc:
            raise MemoryPortabilityError(
                "index_rebuild_queue_failed",
                "Memory index rebuilding could not be queued after restore.",
                status_code=500,
            ) from exc
        state.manager_paused = False
        self.operations.update(
            operation_id,
            phase="rebuilding_indexes",
            progress_percent=90,
            index_rebuild_status="pending",
        )
        index_rebuild_status = str(rebuild_job.get("status") or "pending")
        try:
            await _complete_restore_commit(state.transaction)
        except MemoryPortabilityError as exc:
            if exc.code == "restore_commit_outcome_unknown":
                state.commit_outcome_unknown = True
            raise
        state.committed = True
        try:
            self.operations.succeed(
                operation_id,
                record_counts=dict(manifest.counts),
                safety_backup_path=state.safety_backup_path,
                index_rebuild_status=index_rebuild_status,
            )
        except MemoryPortabilityError:
            logger.warning(
                "Committed memory restore success will be finalized on startup",
                operation_id=operation_id,
                exc_info=True,
            )
            self.operations.resolve_restore_after_startup(
                operation_id,
                outcome="committed",
                safety_backup_path=state.safety_backup_path,
            )
            return
        try:
            await asyncio.to_thread(state.transaction.finalize_commit)
        except Exception:
            logger.warning(
                "Committed memory restore cleanup was deferred",
                operation_id=operation_id,
                exc_info=True,
            )
        try:
            await asyncio.to_thread(
                delete_restore_candidate,
                runtime_paths=self.runtime_paths,
                candidate_id=candidate_id,
            )
        except Exception:
            logger.warning(
                "Committed memory restore candidate cleanup was deferred",
                candidate_id=candidate_id,
                exc_info=True,
            )

    async def _record_restore_failure(
        self,
        *,
        operation_id: str,
        error: BaseException,
        state: _RestoreRuntimeState,
        rebuild_manager: Any,
        initialize_agent_runtime: Any,
        shutdown_agent_runtime: Any,
    ) -> None:
        """Recover live state and persist one secret-free terminal error."""

        recovery_error = await self._recover_restore_runtime(
            state=state,
            rebuild_manager=rebuild_manager,
            initialize_agent_runtime=initialize_agent_runtime,
            shutdown_agent_runtime=shutdown_agent_runtime,
        )
        if recovery_error is not None:
            logger.error(
                "Memory restore recovery failed",
                operation_id=operation_id,
                exc_info=(
                    type(recovery_error),
                    recovery_error,
                    recovery_error.__traceback__,
                ),
            )
            self.operations.fail(
                operation_id,
                code=(
                    "restore_rollback_failed"
                    if state.cutover_attempted
                    else "restore_runtime_recovery_failed"
                ),
                message=(
                    "Memory restore failed and automatic recovery could not complete. "
                    "Restart Magi to finish recovery."
                ),
                rollback_performed=state.rollback_performed,
                safety_backup_path=state.safety_backup_path,
            )
            return
        if isinstance(error, MemoryPortabilityError):
            code = error.code
            message = str(error)
        elif isinstance(error, asyncio.CancelledError):
            code = "operation_cancelled"
            message = "The memory restore operation was cancelled safely."
        else:
            logger.error(
                "Memory restore failed unexpectedly",
                operation_id=operation_id,
                exc_info=(type(error), error, error.__traceback__),
            )
            code = "restore_failed"
            message = "Memory restore could not be completed safely."
        self.operations.fail(
            operation_id,
            code=code,
            message=message,
            rollback_performed=state.rollback_performed,
            safety_backup_path=state.safety_backup_path,
        )

    async def _recover_restore_runtime(
        self,
        *,
        state: _RestoreRuntimeState,
        rebuild_manager: Any,
        initialize_agent_runtime: Any,
        shutdown_agent_runtime: Any,
    ) -> BaseException | None:
        """Rollback a failed cutover and leave the original runtime usable."""

        if state.committed or state.commit_outcome_unknown:
            return None
        try:
            if state.cutover_attempted and not state.manager_paused:
                await rebuild_manager.pause_starts_and_cancel_all()
                state.manager_paused = True
            if state.shutdown_attempted and not state.runtime_offline:
                await shutdown_agent_runtime(strict=True)
                state.runtime_offline = True
            if state.transaction is not None:
                if state.cutover_attempted:
                    await asyncio.to_thread(state.transaction.rollback)
                    state.rollback_performed = True
                else:
                    await asyncio.to_thread(state.transaction.close)
            if state.runtime_offline:
                await initialize_agent_runtime()
                get_unified_memory()
                state.runtime_offline = False
            return None
        except BaseException as recovery_error:
            return recovery_error

    def _archive_directory(self) -> Path:
        try:
            path = Path(get_config().agent.memory.archive_path).expanduser()
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        except (OSError, RuntimeError, TypeError) as exc:
            raise MemoryPortabilityError(
                "archive_target_invalid",
                "The configured memory archive directory is unavailable.",
                status_code=500,
            ) from exc
        return path

    async def _create_consistent_snapshot(self, *, include_l0: bool) -> Any:
        """Snapshot the live archive target while configuration writes are blocked."""

        async with get_embedding_config_update_lock():
            unified_memory = self._optional_unified_memory()
            archive_target = self._archive_directory_for_live_runtime(unified_memory)
            return await create_memory_snapshot(
                runtime_paths=self.runtime_paths,
                archive_dir=archive_target,
                unified_memory=unified_memory,
                include_l0=include_l0,
            )

    async def _capture_archive_target(self) -> Path:
        """Capture one validated archive target for restore inspection."""

        async with get_embedding_config_update_lock():
            return self._archive_directory_for_live_runtime(self._optional_unified_memory())

    def _require_current_archive_target(
        self,
        metadata: dict[str, object],
        unified_memory: Any | None,
    ) -> None:
        """Reject a candidate inspected for a now-stale archive configuration."""

        candidate_value = metadata.get("archive_target")
        if not isinstance(candidate_value, str):
            raise MemoryPortabilityError(
                "candidate_integrity_missing",
                "The restore candidate is missing its archive target.",
            )
        try:
            candidate_target = Path(candidate_value).resolve(strict=True)
            current_target = self._archive_directory_for_live_runtime(unified_memory).resolve(
                strict=True
            )
            target_matches = candidate_target.samefile(current_target)
        except OSError as exc:
            raise MemoryPortabilityError(
                "archive_target_invalid",
                "The configured memory archive directory is unavailable.",
            ) from exc
        if not target_matches:
            raise MemoryPortabilityError(
                "candidate_changed",
                "The memory archive directory changed after this backup was inspected. "
                "Inspect the backup again before restoring it.",
                status_code=409,
            )

    def _archive_directory_for_live_runtime(self, unified_memory: Any | None) -> Path:
        """Require configuration and the active memory store to use one archive path."""

        configured_target = self._archive_directory()
        if unified_memory is None:
            return configured_target
        live_value = getattr(unified_memory, "_archive_dir", None)
        if not isinstance(live_value, (str, Path)):
            raise MemoryPortabilityError(
                "archive_runtime_unavailable",
                "The active memory archive location cannot be verified safely.",
                status_code=503,
            )
        try:
            live_target = Path(live_value).expanduser().resolve(strict=True)
            configured = configured_target.resolve(strict=True)
            target_matches = live_target.samefile(configured)
        except OSError as exc:
            raise MemoryPortabilityError(
                "archive_target_invalid",
                "The configured memory archive directory is unavailable.",
            ) from exc
        if not target_matches:
            raise MemoryPortabilityError(
                "archive_runtime_stale",
                "The memory archive location changed while Magi was running. "
                "Restart Magi before backing up, exporting, or restoring memory.",
                status_code=409,
            )
        return live_target

    @staticmethod
    def _optional_unified_memory() -> Any | None:
        try:
            return get_unified_memory()
        except RuntimeError:
            return None


@asynccontextmanager
async def _runtime_replacement_boundary(unified_memory: Any | None) -> AsyncIterator[None]:
    if unified_memory is None:
        yield
        return
    guard = getattr(unified_memory, "memory_runtime_replacement_guard", None)
    if not callable(guard):
        raise MemoryPortabilityError(
            "restore_runtime_unavailable",
            "The current memory runtime cannot be replaced safely.",
            status_code=503,
        )
    async with guard():
        yield


async def _complete_restore_commit(transaction: Any) -> None:
    """Finish the point-of-no-return and resolve any ambiguous write failure."""

    commit_task = asyncio.create_task(
        asyncio.to_thread(transaction.commit),
        name="memory-restore-durable-commit",
    )
    cancellation_deferred = False
    while not commit_task.done():
        try:
            await asyncio.shield(commit_task)
        except asyncio.CancelledError:
            cancellation_deferred = True
        except BaseException:
            break
    try:
        commit_task.result()
    except BaseException as commit_error:
        try:
            committed = await asyncio.to_thread(transaction.has_installed_commit)
        except BaseException as verification_error:
            raise MemoryPortabilityError(
                "restore_commit_outcome_unknown",
                "The restore commit outcome could not be verified. Restart Magi to finish recovery.",
                status_code=500,
            ) from verification_error
        if not committed:
            raise commit_error
    if cancellation_deferred:
        logger.info("Memory restore cancellation was deferred through durable commit")


def _ready_inspection_payload(inspection: BackupInspection) -> dict[str, Any]:
    if inspection.candidate_id is None or inspection.fingerprint is None:
        raise MemoryPortabilityError(
            "candidate_invalid",
            "The inspected restore candidate is invalid.",
            status_code=500,
        )
    return {
        "state": "ready",
        "candidate_id": inspection.candidate_id,
        "encrypted": bool(inspection.encrypted),
        "format_version": BACKUP_FORMAT_VERSION,
        "magi_version": inspection.magi_version,
        "created_at": inspection.created_at,
        "scope": list(inspection.scope),
        "record_counts": dict(inspection.counts),
        "compatibility": inspection.compatibility,
        "warnings": list(inspection.warnings),
        "expires_at": inspection.expires_at,
        "source_fingerprint": inspection.fingerprint,
    }


_SHARED_SERVICE: MemoryPortabilityService | None = None


def get_memory_portability_service() -> MemoryPortabilityService:
    """Return the process-wide service for the current runtime directory."""

    global _SHARED_SERVICE
    runtime_paths = get_runtime_paths()
    if _SHARED_SERVICE is None or _SHARED_SERVICE.runtime_paths.base_dir != runtime_paths.base_dir:
        _SHARED_SERVICE = MemoryPortabilityService(runtime_paths=runtime_paths)
    return _SHARED_SERVICE


__all__ = ["MemoryPortabilityService", "get_memory_portability_service"]
