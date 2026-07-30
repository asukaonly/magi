"""Background plugin installation job tracking."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import threading
import time
import uuid

from fastapi import HTTPException, status

from ... import i18n as core_i18n
from ...plugins.install_candidates import (
    PluginInstallCandidate,
    PluginInstallCandidateStore,
    get_plugin_install_candidate_store,
)
from ...plugins.install_service import PluginInstallService
from ...plugins.package_files import InvalidPluginArchiveError
from .plugins_common import (
    _get_registry_client,
    _require_plugin_manager,
    _serialize_package,
    _serialize_package_lightweight,
    _try_plugin_manager,
)
from .plugins_schemas import PluginInstallJobSnapshot, PluginInstallLogEntry, PluginPackageResponse

MAX_JOB_LOGS = 240
JOB_RETENTION_SECONDS = 1800


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
    result: PluginPackageResponse | None = None
    logs: list[PluginInstallLogEntry] = field(default_factory=list)
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    finished_at_ms: int | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def append_log(self, level: str, stage: str, message: str) -> None:
        text = message.strip()
        if not text:
            return
        with self.lock:
            self.logs.append(
                PluginInstallLogEntry(
                    ts_ms=int(time.time() * 1000),
                    level=level,
                    stage=stage,
                    message=text,
                )
            )
            if len(self.logs) > MAX_JOB_LOGS:
                self.logs = self.logs[-MAX_JOB_LOGS:]
            self.updated_at_ms = int(time.time() * 1000)

    def update(
        self,
        *,
        stage: str,
        message: str,
        progress_pct: float | None = None,
        level: str = "info",
    ) -> None:
        with self.lock:
            self.status = "running" if self.status == "queued" else self.status
            self.stage = stage
            self.message = message
            if progress_pct is not None:
                self.progress_pct = max(0.0, min(100.0, progress_pct))
            self.updated_at_ms = int(time.time() * 1000)
        self.append_log(level, stage, message)

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

    def fail(self, error: str) -> None:
        with self.lock:
            self.status = "failed"
            self.stage = "failed"
            self.message = "Plugin installation failed"
            self.error = error
            self.finished_at_ms = int(time.time() * 1000)
            self.updated_at_ms = self.finished_at_ms
        self.append_log("error", "failed", error)

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
        self._lock = threading.Lock()

    def get_job(self, job_id: str) -> PluginInstallJobSnapshot | None:
        self._prune_finished_jobs()
        with self._lock:
            job = self._jobs.get(job_id)
        return job.snapshot() if job is not None else None

    def start_registry_install(self, plugin_id: str) -> PluginInstallJobSnapshot:
        job = self._create_job(operation="install", plugin_id=plugin_id)
        self._start_task(job, self._run_registry_install(job))
        return job.snapshot()

    def start_registry_update(self, plugin_id: str) -> PluginInstallJobSnapshot:
        job = self._create_job(operation="update", plugin_id=plugin_id)
        self._start_task(job, self._run_registry_update(job))
        return job.snapshot()

    def start_candidate_install(
        self,
        candidate_id: str,
        *,
        expected_sha256: str,
    ) -> PluginInstallJobSnapshot:
        candidate_store = get_plugin_install_candidate_store()
        candidate = candidate_store.claim(
            candidate_id,
            expected_sha256=expected_sha256,
        )
        job = self._create_job(
            operation="upload",
            plugin_id=candidate.manifest.plugin_id,
            filename=candidate.original_filename,
        )
        install_coro = self._run_candidate_install(job, candidate, candidate_store)
        try:
            self._start_task(job, install_coro)
        except Exception:
            install_coro.close()
            candidate_store.complete(candidate.candidate_id)
            with self._lock:
                self._jobs.pop(job.job_id, None)
            raise
        return job.snapshot()

    def _create_job(
        self,
        *,
        operation: str,
        plugin_id: str | None,
        filename: str | None = None,
    ) -> PluginInstallJob:
        self._prune_finished_jobs()
        job = PluginInstallJob(
            job_id=uuid.uuid4().hex,
            operation=operation,
            plugin_id=plugin_id,
            filename=filename,
        )
        job.append_log("info", "queued", "Queued plugin installation")
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def _start_task(self, job: PluginInstallJob, coro) -> None:
        task = asyncio.create_task(coro)
        with self._lock:
            self._tasks[job.job_id] = task
        task.add_done_callback(lambda _task: self._forget_task(job.job_id))

    def _forget_task(self, job_id: str) -> None:
        with self._lock:
            self._tasks.pop(job_id, None)

    async def _run_registry_install(self, job: PluginInstallJob) -> None:
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
                progress_reporter=self._reporter(job),
            )
            if install_result.extra_installed:
                job.update(
                    stage="install",
                    progress_pct=80.0,
                    message=f"Also installed: {', '.join(install_result.extra_installed)}",
                )
            if install_result.used_runtime_manager:
                job.complete(_serialize_package(install_result.target_state))
            else:
                job.complete(_serialize_package_lightweight(install_result.target_state))
        except Exception as exc:
            job.fail(str(exc))

    async def _run_registry_update(self, job: PluginInstallJob) -> None:
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
                progress_reporter=self._reporter(job),
            )
            job.complete(_serialize_package(new_state))
        except Exception as exc:
            job.fail(str(exc))

    async def _run_candidate_install(
        self,
        job: PluginInstallJob,
        candidate: PluginInstallCandidate,
        candidate_store: PluginInstallCandidateStore,
    ) -> None:
        try:
            manager = _require_plugin_manager()
            install_service = PluginInstallService(
                registry_client=_get_registry_client(),
                plugin_manager=manager,
            )
            job.update(
                stage="upload", progress_pct=10.0, message="Preparing uploaded plugin archive"
            )
            state = await install_service.install_from_archive(
                candidate.archive_path,
                consented_capabilities=candidate.manifest.capabilities,
                progress_reporter=self._reporter(job),
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
        except Exception as exc:
            job.fail(str(exc))
        finally:
            await asyncio.to_thread(candidate_store.complete, candidate.candidate_id)

    @staticmethod
    def _reporter(job: PluginInstallJob):
        def report(stage: str, message: str, progress_pct: float | None = None) -> None:
            job.update(stage=stage, message=message, progress_pct=progress_pct)

        return report

    def _prune_finished_jobs(self) -> None:
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


__all__ = ["plugin_install_jobs", "require_plugin_install_job", "PluginInstallJobManager"]
