"""Background plugin installation job tracking."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import tempfile
import threading
import time
import uuid

from fastapi import HTTPException, status

from ... import i18n as core_i18n
from ...plugins.operation_execution import run_plugin_preparation_operation
from ...plugins.dependency_installation import (
    DependencyInstallResourceLimitError,
    PluginInstallWorkflowTimeoutError,
)
from ...plugins.install_admission import (
    MAX_ACTIVE_PLUGIN_INSTALLS,
    PluginInstallAdmissionLease,
    PluginInstallCapacityError,
    PluginInstallConflictError,
    plugin_install_admission,
)
from ...plugins.install_candidates import (
    PluginInstallCandidate,
    PluginInstallCandidateStore,
    get_plugin_install_candidate_store,
)
from ...plugins.install_service import (
    PluginInstallService,
    PluginPackageConflictError,
    PluginRegistrySourceConflictError,
    PluginRegistrySnapshotMismatchError,
    PluginRegistryVersionError,
)
from ...plugins.package_files import InvalidPluginArchiveError
from .plugins_common import (
    _get_registry_client,
    _require_plugin_manager,
    _serialize_package,
    _try_plugin_manager,
)
from .plugins_schemas import PluginInstallJobSnapshot, PluginInstallLogEntry, PluginPackageResponse

MAX_JOB_LOGS = 240
MAX_JOB_LOG_ENTRY_BYTES = 4 * 1024
MAX_JOB_ERROR_BYTES = 16 * 1024
MAX_JOB_LOG_TOTAL_BYTES = 256 * 1024
MAX_JOB_LOG_STAGE_BYTES = 256
JOB_RETENTION_SECONDS = 1800
MAX_ACTIVE_PLUGIN_INSTALL_JOBS = MAX_ACTIVE_PLUGIN_INSTALLS
MAX_RETAINED_PLUGIN_INSTALL_JOBS = 128
PluginInstallJobCapacityError = PluginInstallCapacityError
PluginInstallJobConflictError = PluginInstallConflictError


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """Return valid UTF-8 text bounded by its encoded byte length."""

    encoded = str(value).encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return encoded.decode("utf-8")
    marker = "…".encode("utf-8")
    prefix_budget = max(0, max_bytes - len(marker))
    prefix = encoded[:prefix_budget].decode("utf-8", errors="ignore")
    if max_bytes < len(marker):
        return encoded[:max_bytes].decode("utf-8", errors="ignore")
    return f"{prefix}…"


def _log_entry_utf8_size(entry: PluginInstallLogEntry) -> int:
    return sum(len(value.encode("utf-8")) for value in (entry.level, entry.stage, entry.message))


@dataclass(slots=True)
class PluginInstallJob:
    job_id: str
    operation: str
    plugin_id: str | None
    filename: str | None = None
    status: str = "queued"
    stage: str = "queued"
    progress_pct: float = 0.0
    message: str = "Queued plugin installation"
    error: str | None = None
    error_code: str | None = None
    result: PluginPackageResponse | None = None
    logs: list[PluginInstallLogEntry] = field(default_factory=list)
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    finished_at_ms: int | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    admission_lease: PluginInstallAdmissionLease | None = field(default=None, repr=False)

    def append_log(self, level: str, stage: str, message: str) -> None:
        text = str(message).strip()
        if not text:
            return
        normalized_stage = _truncate_utf8(
            str(stage).strip() or "unknown",
            MAX_JOB_LOG_STAGE_BYTES,
        )
        message_budget = max(
            0,
            MAX_JOB_LOG_ENTRY_BYTES
            - len(str(level).encode("utf-8", errors="replace"))
            - len(normalized_stage.encode("utf-8")),
        )
        normalized_message = _truncate_utf8(text, message_budget)
        with self.lock:
            self.logs.append(
                PluginInstallLogEntry(
                    ts_ms=int(time.time() * 1000),
                    level=level,
                    stage=normalized_stage,
                    message=normalized_message,
                )
            )
            retained_bytes = sum(_log_entry_utf8_size(entry) for entry in self.logs)
            while self.logs and (
                len(self.logs) > MAX_JOB_LOGS or retained_bytes > MAX_JOB_LOG_TOTAL_BYTES
            ):
                removed = self.logs.pop(0)
                retained_bytes -= _log_entry_utf8_size(removed)
            self.updated_at_ms = int(time.time() * 1000)

    def update(
        self,
        *,
        stage: str,
        message: str,
        progress_pct: float | None = None,
        level: str = "info",
    ) -> None:
        normalized_stage = _truncate_utf8(
            str(stage).strip() or "unknown",
            MAX_JOB_LOG_STAGE_BYTES,
        )
        normalized_message = _truncate_utf8(
            str(message).strip(),
            MAX_JOB_LOG_ENTRY_BYTES,
        )
        with self.lock:
            self.status = "running" if self.status == "queued" else self.status
            self.stage = normalized_stage
            self.message = normalized_message
            if progress_pct is not None:
                self.progress_pct = max(0.0, min(100.0, progress_pct))
            self.updated_at_ms = int(time.time() * 1000)
        self.append_log(level, normalized_stage, normalized_message)

    def complete(self, result: PluginPackageResponse) -> None:
        with self.lock:
            self.status = "completed"
            self.stage = "completed"
            self.progress_pct = 100.0
            self.message = "Plugin installation completed"
            self.result = result
            self.finished_at_ms = int(time.time() * 1000)
            self.updated_at_ms = self.finished_at_ms
        self.append_log("info", "completed", "Plugin installation completed")

    def fail(self, error: str, *, error_code: str | None = None) -> None:
        normalized_error = _truncate_utf8(
            str(error).strip(),
            MAX_JOB_ERROR_BYTES,
        )
        with self.lock:
            self.status = "failed"
            self.stage = "failed"
            self.message = "Plugin installation failed"
            self.error = normalized_error
            self.error_code = error_code
            self.finished_at_ms = int(time.time() * 1000)
            self.updated_at_ms = self.finished_at_ms
        self.append_log("error", "failed", normalized_error)

    def snapshot(self) -> PluginInstallJobSnapshot:
        with self.lock:
            return PluginInstallJobSnapshot(
                job_id=self.job_id,
                operation=self.operation,
                plugin_id=self.plugin_id,
                filename=self.filename,
                status=self.status,
                stage=self.stage,
                progress_pct=self.progress_pct,
                message=self.message,
                error=self.error,
                error_code=self.error_code,
                logs=list(self.logs),
                result=self.result,
                created_at_ms=self.created_at_ms,
                updated_at_ms=self.updated_at_ms,
                finished_at_ms=self.finished_at_ms,
            )


class PluginInstallJobManager:
    """Runs plugin installs in background tasks and exposes pollable snapshots."""

    def __init__(self) -> None:
        self._jobs: dict[str, PluginInstallJob] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._candidate_claim_tasks: set[asyncio.Task[PluginInstallCandidate]] = set()
        self._lock = threading.Lock()

    def get_job(self, job_id: str) -> PluginInstallJobSnapshot | None:
        self._prune_finished_jobs()
        with self._lock:
            job = self._jobs.get(job_id)
        return job.snapshot() if job is not None else None

    async def start_registry_install(
        self,
        plugin_id: str,
        *,
        expected_fingerprint: str,
    ) -> PluginInstallJobSnapshot:
        plugin_id = plugin_install_admission.validate_plugin_id(plugin_id)
        job = self._create_job(operation="install", plugin_id=plugin_id)
        install_coro = self._run_registry_install(job, expected_fingerprint)
        try:
            self._start_task(job, install_coro)
        except Exception:
            install_coro.close()
            self._discard_job(job.job_id)
            raise
        return job.snapshot()

    async def start_registry_update(
        self,
        plugin_id: str,
        *,
        expected_fingerprint: str,
    ) -> PluginInstallJobSnapshot:
        plugin_id = plugin_install_admission.validate_plugin_id(plugin_id)
        job = self._create_job(operation="update", plugin_id=plugin_id)
        install_coro = self._run_registry_update(job, expected_fingerprint)
        try:
            self._start_task(job, install_coro)
        except Exception:
            install_coro.close()
            self._discard_job(job.job_id)
            raise
        return job.snapshot()

    async def start_candidate_install(
        self,
        candidate_id: str,
        *,
        expected_sha256: str,
    ) -> PluginInstallJobSnapshot:
        candidate_store = get_plugin_install_candidate_store()
        preview = candidate_store.get(candidate_id)
        job = self._create_job(
            operation="upload",
            plugin_id=preview.manifest.plugin_id,
            filename=preview.original_filename,
        )
        claim_aborted = threading.Event()

        def claim_candidate() -> PluginInstallCandidate:
            if claim_aborted.is_set():
                candidate_store.complete(candidate_id)
                raise RuntimeError("Plugin install candidate claim was cancelled")
            candidate = candidate_store.claim(
                candidate_id,
                expected_sha256=expected_sha256,
            )
            if claim_aborted.is_set():
                candidate_store.complete(candidate.candidate_id)
            return candidate

        claim_task = asyncio.create_task(run_plugin_preparation_operation(claim_candidate))
        self._candidate_claim_tasks.add(claim_task)
        claim_task.add_done_callback(self._candidate_claim_tasks.discard)
        try:
            candidate = await asyncio.shield(claim_task)
        except BaseException:
            claim_aborted.set()
            self._discard_job(job.job_id)
            claim_task.add_done_callback(
                lambda completed: self._cleanup_cancelled_candidate_claim(
                    completed,
                    candidate_store,
                )
            )
            raise

        install_coro = self._run_candidate_install(job, candidate, candidate_store)
        try:
            self._start_task(job, install_coro)
        except Exception:
            install_coro.close()
            candidate_store.complete(candidate.candidate_id)
            self._discard_job(job.job_id)
            raise
        return job.snapshot()

    @staticmethod
    def _cleanup_cancelled_candidate_claim(
        claim_task: asyncio.Task[PluginInstallCandidate],
        candidate_store: PluginInstallCandidateStore,
    ) -> None:
        if claim_task.cancelled():
            return
        try:
            candidate = claim_task.result()
        except BaseException:
            return
        try:
            candidate_store.complete(candidate.candidate_id)
        except Exception:
            return

    def _create_job(
        self,
        *,
        operation: str,
        plugin_id: str | None,
        filename: str | None = None,
    ) -> PluginInstallJob:
        self._prune_finished_jobs(reserve_slots=1)
        if plugin_id is None:
            raise ValueError("Plugin id is required for installation jobs")
        admission_lease = plugin_install_admission.acquire(plugin_id)
        try:
            job = PluginInstallJob(
                job_id=uuid.uuid4().hex,
                operation=operation,
                plugin_id=admission_lease.plugin_id,
                filename=filename,
                admission_lease=admission_lease,
            )
            job.append_log("info", "queued", "Queued plugin installation")
            with self._lock:
                self._jobs[job.job_id] = job
        except BaseException:
            admission_lease.release()
            raise
        return job

    def _start_task(self, job: PluginInstallJob, coro) -> None:
        task = asyncio.create_task(coro)
        with self._lock:
            self._tasks[job.job_id] = task
        task.add_done_callback(lambda _task: self._forget_task(job.job_id))

    def _forget_task(self, job_id: str) -> None:
        with self._lock:
            self._tasks.pop(job_id, None)

    def _discard_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.pop(job_id, None)
            self._tasks.pop(job_id, None)
        if job is not None and job.admission_lease is not None:
            job.admission_lease.release()

    async def _run_registry_install(
        self,
        job: PluginInstallJob,
        expected_fingerprint: str,
    ) -> None:
        try:
            plugin_id = job.plugin_id or ""
            registry = _get_registry_client()
            job.update(
                stage="registry", progress_pct=8.0, message="Resolving plugin registry entry"
            )
            manager = _try_plugin_manager()
            install_service = PluginInstallService(
                registry_client=registry,
                plugin_manager=manager,
            )
            job.update(stage="install", progress_pct=20.0, message="Resolving plugin dependencies")
            install_result = await install_service.install_from_registry(
                plugin_id,
                expected_fingerprint=expected_fingerprint,
                progress_reporter=self._reporter(job),
                admission_lease=job.admission_lease,
            )
            if install_result.extra_installed:
                job.update(
                    stage="install",
                    progress_pct=80.0,
                    message=f"Also installed: {', '.join(install_result.extra_installed)}",
                )
            job.complete(_serialize_package(install_result.target_state))
        except PluginRegistrySnapshotMismatchError:
            job.fail(
                core_i18n.t(
                    "plugins.errors.registry_changed",
                    fallback="Marketplace information changed. Review it again before continuing.",
                ),
                error_code="PLUGIN_REGISTRY_CHANGED",
            )
        except PluginRegistryVersionError as exc:
            job.fail(str(exc), error_code="PLUGIN_VERSION_NOT_ADVANCED")
        except (PluginPackageConflictError, PluginRegistrySourceConflictError):
            job.fail(
                core_i18n.t(
                    "plugins.errors.package_source_conflict",
                    fallback=(
                        "This plugin is already installed from another source. "
                        "Uninstall it before continuing."
                    ),
                ),
                error_code="PLUGIN_PACKAGE_CONFLICT",
            )
        except PluginInstallWorkflowTimeoutError:
            job.fail(
                core_i18n.t(
                    "plugins.errors.install_timeout",
                    fallback="Plugin installation took too long and was stopped",
                ),
                error_code="PLUGIN_INSTALL_TIMEOUT",
            )
        except DependencyInstallResourceLimitError:
            job.fail(
                core_i18n.t(
                    "plugins.errors.install_resource_limit",
                    fallback="Plugin installation exceeded the allowed resource limit",
                ),
                error_code="PLUGIN_INSTALL_RESOURCE_LIMIT",
            )
        except asyncio.CancelledError:
            job.fail("Plugin installation was cancelled")
            raise
        except Exception as exc:
            job.fail(str(exc))
        finally:
            if job.admission_lease is not None:
                job.admission_lease.release()

    async def _run_registry_update(
        self,
        job: PluginInstallJob,
        expected_fingerprint: str,
    ) -> None:
        try:
            plugin_id = job.plugin_id or ""
            registry = _get_registry_client()
            install_service = PluginInstallService(
                registry_client=registry,
                plugin_manager=_require_plugin_manager(),
            )
            job.update(
                stage="registry", progress_pct=8.0, message="Resolving plugin registry entry"
            )
            job.update(stage="download", progress_pct=18.0, message="Downloading plugin source")
            job.update(stage="install", progress_pct=35.0, message="Updating plugin package")
            new_state = await install_service.update_from_registry(
                plugin_id,
                expected_fingerprint=expected_fingerprint,
                progress_reporter=self._reporter(job),
                admission_lease=job.admission_lease,
            )
            job.complete(_serialize_package(new_state))
        except PluginRegistrySnapshotMismatchError:
            job.fail(
                core_i18n.t(
                    "plugins.errors.registry_changed",
                    fallback="Marketplace information changed. Review it again before continuing.",
                ),
                error_code="PLUGIN_REGISTRY_CHANGED",
            )
        except PluginRegistryVersionError as exc:
            job.fail(str(exc), error_code="PLUGIN_VERSION_NOT_ADVANCED")
        except (PluginPackageConflictError, PluginRegistrySourceConflictError):
            job.fail(
                core_i18n.t(
                    "plugins.errors.package_source_conflict",
                    fallback=(
                        "This plugin is already installed from another source. "
                        "Uninstall it before continuing."
                    ),
                ),
                error_code="PLUGIN_PACKAGE_CONFLICT",
            )
        except PluginInstallWorkflowTimeoutError:
            job.fail(
                core_i18n.t(
                    "plugins.errors.install_timeout",
                    fallback="Plugin installation took too long and was stopped",
                ),
                error_code="PLUGIN_INSTALL_TIMEOUT",
            )
        except DependencyInstallResourceLimitError:
            job.fail(
                core_i18n.t(
                    "plugins.errors.install_resource_limit",
                    fallback="Plugin installation exceeded the allowed resource limit",
                ),
                error_code="PLUGIN_INSTALL_RESOURCE_LIMIT",
            )
        except asyncio.CancelledError:
            job.fail("Plugin installation was cancelled")
            raise
        except Exception as exc:
            job.fail(str(exc))
        finally:
            if job.admission_lease is not None:
                job.admission_lease.release()

    async def _run_candidate_install(
        self,
        job: PluginInstallJob,
        candidate: PluginInstallCandidate,
        candidate_store: PluginInstallCandidateStore,
    ) -> None:
        try:
            archive_bytes = candidate.archive_bytes
            if (
                archive_bytes is None
                or hashlib.sha256(archive_bytes).hexdigest() != candidate.archive_sha256
            ):
                raise InvalidPluginArchiveError(
                    "Approved plugin archive snapshot is unavailable or has changed"
                )
            manager = _require_plugin_manager()
            install_service = PluginInstallService(
                registry_client=_get_registry_client(),
                plugin_manager=manager,
            )
            job.update(
                stage="upload", progress_pct=10.0, message="Preparing uploaded plugin archive"
            )
            with tempfile.TemporaryDirectory(prefix="magi-plugin-approved-") as tmp:
                archive_path = Path(tmp) / f"archive{candidate.archive_suffix}"
                archive_path.write_bytes(archive_bytes)
                archive_path.chmod(0o400)
                state = await install_service.install_from_archive(
                    archive_path,
                    approved_manifest=candidate.manifest,
                    approved_package_sha256=candidate.package_sha256,
                    consented_capabilities=candidate.manifest.capabilities,
                    progress_reporter=self._reporter(job),
                    admission_lease=job.admission_lease,
                )
            with job.lock:
                job.plugin_id = state.manifest.plugin_id
            job.complete(_serialize_package(state))
        except InvalidPluginArchiveError:
            job.fail(
                core_i18n.t(
                    "plugins.errors.archive_invalid",
                    fallback="The uploaded file is not a valid plugin archive",
                )
            )
        except PluginInstallWorkflowTimeoutError:
            job.fail(
                core_i18n.t(
                    "plugins.errors.install_timeout",
                    fallback="Plugin installation took too long and was stopped",
                ),
                error_code="PLUGIN_INSTALL_TIMEOUT",
            )
        except DependencyInstallResourceLimitError:
            job.fail(
                core_i18n.t(
                    "plugins.errors.install_resource_limit",
                    fallback="Plugin installation exceeded the allowed resource limit",
                ),
                error_code="PLUGIN_INSTALL_RESOURCE_LIMIT",
            )
        except asyncio.CancelledError:
            job.fail("Plugin installation was cancelled")
            raise
        except Exception as exc:
            job.fail(str(exc))
        finally:
            if job.admission_lease is not None:
                job.admission_lease.release()
            await run_plugin_preparation_operation(
                lambda: candidate_store.complete(candidate.candidate_id)
            )

    @staticmethod
    def _reporter(job: PluginInstallJob):
        def report(stage: str, message: str, progress_pct: float | None = None) -> None:
            job.update(stage=stage, message=message, progress_pct=progress_pct)

        return report

    def _prune_finished_jobs(self, *, reserve_slots: int = 0) -> None:
        cutoff_ms = int((time.time() - JOB_RETENTION_SECONDS) * 1000)
        with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.finished_at_ms is not None and job.finished_at_ms < cutoff_ms
            ]
            for job_id in expired:
                self._jobs.pop(job_id, None)
                self._tasks.pop(job_id, None)

            target_size = max(0, MAX_RETAINED_PLUGIN_INSTALL_JOBS - reserve_slots)
            overflow = len(self._jobs) - target_size
            if overflow <= 0:
                return
            oldest_finished = sorted(
                (job for job in self._jobs.values() if job.finished_at_ms is not None),
                key=lambda job: (job.finished_at_ms or 0, job.created_at_ms),
            )
            for job in oldest_finished[:overflow]:
                self._jobs.pop(job.job_id, None)
                self._tasks.pop(job.job_id, None)


plugin_install_jobs = PluginInstallJobManager()


def require_plugin_install_job(job_id: str) -> PluginInstallJobSnapshot:
    snapshot = plugin_install_jobs.get_job(job_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "plugins.errors.install_job_not_found",
                fallback="Plugin installation job not found",
            ),
        )
    return snapshot


__all__ = [
    "MAX_ACTIVE_PLUGIN_INSTALL_JOBS",
    "MAX_JOB_ERROR_BYTES",
    "MAX_JOB_LOG_ENTRY_BYTES",
    "MAX_JOB_LOG_TOTAL_BYTES",
    "MAX_JOB_LOGS",
    "MAX_RETAINED_PLUGIN_INSTALL_JOBS",
    "PluginInstallJobCapacityError",
    "PluginInstallJobConflictError",
    "PluginInstallJobManager",
    "plugin_install_jobs",
    "require_plugin_install_job",
]
