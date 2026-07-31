from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import tempfile
import threading

import pytest

from magi.api.routers import plugins_install_jobs
from magi.api.routers.plugins_install_jobs import (
    MAX_ACTIVE_PLUGIN_INSTALL_JOBS,
    MAX_JOB_ERROR_BYTES,
    MAX_JOB_LOG_ENTRY_BYTES,
    MAX_JOB_LOG_TOTAL_BYTES,
    MAX_JOB_LOGS,
    MAX_RETAINED_PLUGIN_INSTALL_JOBS,
    PluginInstallJob,
    PluginInstallJobCapacityError,
    PluginInstallJobConflictError,
    PluginInstallJobManager,
)
from magi.api.routers.plugins_schemas import PluginManifestResponse, PluginPackageResponse
from magi.plugins.contracts import (
    PluginCapability,
    PluginManifest,
    PluginPackageState,
    PluginPermissions,
)
from magi.plugins.dependency_installation import (
    DependencyInstallResourceLimitError,
    PluginInstallWorkflowTimeoutError,
)
from magi.plugins.install_candidates import (
    PluginInstallCandidateClaimedError,
    PluginInstallCandidateNotFoundError,
    PluginInstallCandidateStore,
)
from magi.plugins.install_service import (
    PluginInstallApprovalMismatchError,
    PluginInstallService,
    PluginSideloadConflictError,
)
from magi.plugins.install_admission import PluginInstallAdmissionCoordinator
from magi.plugins.installation import PluginArchiveInspection
from magi.plugins.package_identity import compute_package_sha256


def _manifest() -> PluginManifest:
    return PluginManifest(
        id="demo-plugin",
        name="Demo Plugin",
        version="1.0.0",
        permissions=PluginPermissions(
            capabilities=[
                PluginCapability(
                    capability="network",
                    scope=["example.com"],
                )
            ]
        ),
    )


def _package_sha256() -> str:
    with tempfile.TemporaryDirectory(prefix="magi-candidate-job-package-") as tmp:
        package_dir = Path(tmp)
        (package_dir / "plugin.toml").write_text(
            '[plugin]\nid = "demo-plugin"\nname = "Demo Plugin"\nversion = "1.0.0"\n',
            encoding="utf-8",
        )
        (package_dir / "plugin.py").write_text("VALUE = 1\n", encoding="utf-8")
        return compute_package_sha256(package_dir)


def _registered_candidate(store: PluginInstallCandidateStore):
    candidate_id, archive_path = store.reserve_archive(".zip")
    archive_path.write_bytes(b"archive")
    return store.register(
        candidate_id=candidate_id,
        archive_path=archive_path,
        original_filename="demo.zip",
        archive_sha256=hashlib.sha256(b"archive").hexdigest(),
        package_sha256=_package_sha256(),
        manifest=_manifest(),
    )


def _package_response(state: PluginPackageState) -> PluginPackageResponse:
    return PluginPackageResponse(
        manifest=PluginManifestResponse(
            plugin_id=state.manifest.plugin_id,
            name=state.manifest.name,
            version=state.manifest.version,
            description="",
            author=state.manifest.author,
            official=False,
            contribution_types=[],
            source="external",
            plugin_dir="",
            manifest_path="",
            capabilities=state.manifest.capabilities,
        ),
        enabled=False,
        trusted=False,
        loaded=False,
        healthy=True,
    )


def _retained_log_bytes(job: PluginInstallJob) -> int:
    return sum(
        len(value.encode("utf-8"))
        for entry in job.logs
        for value in (entry.level, entry.stage, entry.message)
    )


def test_job_truncates_oversized_log_without_splitting_utf8() -> None:
    job = PluginInstallJob(
        job_id="job-log-limit",
        operation="install",
        plugin_id="demo-plugin",
    )

    job.update(
        stage="下载",
        message=("日志🙂" * 4_000) + "\ud800",
        progress_pct=25,
    )

    assert len(job.logs) == 1
    entry = job.logs[0]
    assert (
        len(
            entry.level.encode("utf-8")
            + entry.stage.encode("utf-8")
            + entry.message.encode("utf-8")
        )
        <= MAX_JOB_LOG_ENTRY_BYTES
    )
    assert len(job.message.encode("utf-8")) <= MAX_JOB_LOG_ENTRY_BYTES
    assert entry.message.endswith("…")
    assert "\ud800" not in entry.message
    assert entry.message.encode("utf-8").decode("utf-8") == entry.message


def test_job_truncates_oversized_utf8_exception_text() -> None:
    job = PluginInstallJob(
        job_id="job-error-limit",
        operation="install",
        plugin_id="demo-plugin",
    )
    exception = RuntimeError(("安装失败🙂" * 8_000) + "\ud800")

    job.fail(str(exception))

    assert job.error is not None
    assert len(job.error.encode("utf-8")) <= MAX_JOB_ERROR_BYTES
    assert job.error.endswith("…")
    assert "\ud800" not in job.error
    assert job.logs[-1].level == "error"
    assert _retained_log_bytes(job) <= MAX_JOB_LOG_ENTRY_BYTES


def test_job_bounds_retained_log_bytes_and_count() -> None:
    job = PluginInstallJob(
        job_id="job-retained-log-limit",
        operation="install",
        plugin_id="demo-plugin",
    )

    for index in range(100):
        job.append_log("info", "install", f"{index:03d}:" + ("界" * 4_000))

    assert _retained_log_bytes(job) <= MAX_JOB_LOG_TOTAL_BYTES
    assert len(job.logs) < 100
    assert job.logs[-1].message.startswith("099:")

    for index in range(300):
        job.append_log("info", "install", f"small-{index}")

    assert len(job.logs) == MAX_JOB_LOGS
    assert _retained_log_bytes(job) <= MAX_JOB_LOG_TOTAL_BYTES
    assert job.logs[-1].message == "small-299"


def test_job_admission_bounds_active_jobs_and_enforces_single_flight() -> None:
    manager = PluginInstallJobManager()
    jobs = [
        manager._create_job(operation="install", plugin_id=f"plugin-{index}")
        for index in range(MAX_ACTIVE_PLUGIN_INSTALL_JOBS)
    ]
    try:
        with pytest.raises(PluginInstallJobCapacityError):
            manager._create_job(operation="install", plugin_id="overflow")
        with pytest.raises(PluginInstallJobConflictError):
            manager._create_job(operation="update", plugin_id="plugin-0")
    finally:
        for job in jobs:
            assert job.admission_lease is not None
            job.admission_lease.release()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["install", "update"])
async def test_registry_jobs_reject_overflow_before_registry_read(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    manager = PluginInstallJobManager()
    jobs = [
        manager._create_job(operation="install", plugin_id=f"plugin-{index}")
        for index in range(MAX_ACTIVE_PLUGIN_INSTALL_JOBS)
    ]
    monkeypatch.setattr(
        plugins_install_jobs,
        "_get_registry_client",
        lambda: pytest.fail("Registry must not be read before install admission"),
    )

    try:
        with pytest.raises(PluginInstallJobCapacityError):
            if operation == "install":
                await manager.start_registry_install(
                    "overflow-plugin",
                    expected_fingerprint="a" * 64,
                )
            else:
                await manager.start_registry_update(
                    "overflow-plugin",
                    expected_fingerprint="a" * 64,
                )
    finally:
        for job in jobs:
            manager._discard_job(job.job_id)


@pytest.mark.parametrize(
    "plugin_id",
    [
        "",
        "a" * 65,
        "Demo-Plugin",
        "con",
        "../demo-plugin",
        " demo-plugin ",
    ],
)
def test_install_admission_rejects_invalid_plugin_identifiers(plugin_id: str) -> None:
    coordinator = PluginInstallAdmissionCoordinator()

    with pytest.raises(ValueError, match="Invalid plugin id"):
        coordinator.acquire(plugin_id)

    assert coordinator.active_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["install", "update"])
async def test_invalid_registry_job_target_is_rejected_before_registry_read(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    monkeypatch.setattr(
        plugins_install_jobs,
        "_get_registry_client",
        lambda: pytest.fail("Registry must not be read for an invalid plugin id"),
    )
    manager = PluginInstallJobManager()

    with pytest.raises(ValueError, match="Invalid plugin id"):
        if operation == "install":
            await manager.start_registry_install(
                "../invalid",
                expected_fingerprint="a" * 64,
            )
        else:
            await manager.start_registry_update(
                "../invalid",
                expected_fingerprint="a" * 64,
            )


def test_finished_job_records_remain_bounded() -> None:
    manager = PluginInstallJobManager()
    created_ids: list[str] = []

    for index in range(MAX_RETAINED_PLUGIN_INSTALL_JOBS + 20):
        job = manager._create_job(
            operation="install",
            plugin_id=f"finished-plugin-{index}",
        )
        created_ids.append(job.job_id)
        job.finished_at_ms = index + 1
        assert job.admission_lease is not None
        job.admission_lease.release()

    assert len(manager._jobs) <= MAX_RETAINED_PLUGIN_INSTALL_JOBS
    assert created_ids[0] not in manager._jobs
    assert created_ids[-1] in manager._jobs


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["install", "update"])
async def test_cancelled_registry_runner_finishes_job(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    started = asyncio.Event()

    class _BlockingInstallService:
        def __init__(self, **_kwargs):
            pass

        async def install_from_registry(self, *_args, **_kwargs):
            started.set()
            await asyncio.Event().wait()

        async def update_from_registry(self, *_args, **_kwargs):
            started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(
        plugins_install_jobs,
        "PluginInstallService",
        _BlockingInstallService,
    )
    monkeypatch.setattr(plugins_install_jobs, "_get_registry_client", object)
    monkeypatch.setattr(plugins_install_jobs, "_try_plugin_manager", lambda: object())
    monkeypatch.setattr(plugins_install_jobs, "_require_plugin_manager", object)
    manager = PluginInstallJobManager()
    job = PluginInstallJob(
        job_id=f"cancelled-{operation}",
        operation=operation,
        plugin_id="demo-plugin",
    )
    runner = (
        manager._run_registry_install(job, "a" * 64)
        if operation == "install"
        else manager._run_registry_update(job, "a" * 64)
    )
    task = asyncio.create_task(runner)
    await started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert job.status == "failed"
    assert job.finished_at_ms is not None
    assert job.error == "Plugin installation was cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_code", "expected_key"),
    [
        (
            PluginInstallWorkflowTimeoutError("internal timeout"),
            "PLUGIN_INSTALL_TIMEOUT",
            "plugins.errors.install_timeout",
        ),
        (
            DependencyInstallResourceLimitError("internal resource detail"),
            "PLUGIN_INSTALL_RESOURCE_LIMIT",
            "plugins.errors.install_resource_limit",
        ),
    ],
)
async def test_registry_runner_localizes_install_limits(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_code: str,
    expected_key: str,
) -> None:
    class _FailingInstallService:
        def __init__(self, **_kwargs):
            pass

        async def install_from_registry(self, *_args, **_kwargs):
            raise error

    monkeypatch.setattr(
        plugins_install_jobs,
        "PluginInstallService",
        _FailingInstallService,
    )
    monkeypatch.setattr(plugins_install_jobs, "_get_registry_client", object)
    monkeypatch.setattr(plugins_install_jobs, "_try_plugin_manager", lambda: object())
    monkeypatch.setattr(
        plugins_install_jobs.core_i18n,
        "t",
        lambda key, **_kwargs: key,
    )
    manager = PluginInstallJobManager()
    job = PluginInstallJob(
        job_id="bounded-install",
        operation="install",
        plugin_id="demo-plugin",
    )

    await manager._run_registry_install(job, "a" * 64)

    assert job.status == "failed"
    assert job.error_code == expected_code
    assert job.error == expected_key


@pytest.mark.asyncio
async def test_cancelled_candidate_runner_finishes_job_and_cleans_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = PluginInstallCandidateStore(tmp_path / "cancelled-runner")
    candidate = _registered_candidate(store)
    candidate = store.claim(
        candidate.candidate_id,
        expected_sha256=candidate.archive_sha256,
    )
    started = asyncio.Event()

    class _BlockingInstallService:
        def __init__(self, **_kwargs):
            pass

        async def install_from_archive(self, *_args, **_kwargs):
            started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(
        plugins_install_jobs,
        "PluginInstallService",
        _BlockingInstallService,
    )
    monkeypatch.setattr(plugins_install_jobs, "_get_registry_client", object)
    monkeypatch.setattr(plugins_install_jobs, "_require_plugin_manager", object)
    manager = PluginInstallJobManager()
    job = PluginInstallJob(
        job_id="cancelled-upload",
        operation="upload",
        plugin_id="demo-plugin",
    )
    task = asyncio.create_task(manager._run_candidate_install(job, candidate, store))
    await started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert job.status == "failed"
    assert job.finished_at_ms is not None
    assert job.error == "Plugin installation was cancelled"
    with pytest.raises(PluginInstallCandidateNotFoundError):
        store.get(candidate.candidate_id)


@pytest.mark.asyncio
async def test_job_start_claims_candidate_and_rejects_replay(monkeypatch, tmp_path):
    store = PluginInstallCandidateStore(tmp_path / "candidates")
    candidate = _registered_candidate(store)
    manager = PluginInstallJobManager()

    def capture_without_running(job, install_coro):
        install_coro.close()
        job.admission_lease.release()

    monkeypatch.setattr(
        plugins_install_jobs,
        "get_plugin_install_candidate_store",
        lambda: store,
    )
    monkeypatch.setattr(manager, "_start_task", capture_without_running)

    snapshot = await manager.start_candidate_install(
        candidate.candidate_id,
        expected_sha256=candidate.archive_sha256,
    )

    assert snapshot.filename == "demo.zip"
    assert snapshot.plugin_id == "demo-plugin"
    with pytest.raises(PluginInstallCandidateClaimedError):
        await manager.start_candidate_install(
            candidate.candidate_id,
            expected_sha256=candidate.archive_sha256,
        )


@pytest.mark.asyncio
async def test_cancelled_candidate_claims_release_capacity_and_cleanup(
    monkeypatch,
    tmp_path,
) -> None:
    store = PluginInstallCandidateStore(tmp_path / "cancelled-candidates")
    manager = PluginInstallJobManager()
    candidates = [_registered_candidate(store) for _ in range(MAX_ACTIVE_PLUGIN_INSTALL_JOBS)]
    original_claim = store.claim
    claim_completed = threading.Event()
    release_claim = threading.Event()

    def claim_then_block(candidate_id: str, *, expected_sha256: str):
        candidate = original_claim(
            candidate_id,
            expected_sha256=expected_sha256,
        )
        claim_completed.set()
        if not release_claim.wait(timeout=5):
            raise TimeoutError("Timed out waiting to release candidate claim")
        return candidate

    monkeypatch.setattr(
        plugins_install_jobs,
        "get_plugin_install_candidate_store",
        lambda: store,
    )
    monkeypatch.setattr(store, "claim", claim_then_block)

    try:
        for index, candidate in enumerate(candidates):
            start_task = asyncio.create_task(
                manager.start_candidate_install(
                    candidate.candidate_id,
                    expected_sha256=candidate.archive_sha256,
                )
            )
            await asyncio.sleep(0)
            if index == 0:
                assert await asyncio.to_thread(claim_completed.wait, 1)
            start_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await start_task

        assert manager._jobs == {}

        probe_jobs = [
            manager._create_job(
                operation="install",
                plugin_id=f"cancel-probe-{index}",
            )
            for index in range(MAX_ACTIVE_PLUGIN_INSTALL_JOBS)
        ]
        for probe in probe_jobs:
            manager._discard_job(probe.job_id)
    finally:
        release_claim.set()

    for _ in range(500):
        if not manager._candidate_claim_tasks:
            break
        await asyncio.sleep(0.01)
    assert not manager._candidate_claim_tasks
    await asyncio.sleep(0)

    for candidate in candidates:
        with pytest.raises(PluginInstallCandidateNotFoundError):
            store.get(candidate.candidate_id)


@pytest.mark.asyncio
async def test_job_installs_exact_candidate_and_always_removes_it(monkeypatch, tmp_path):
    store = PluginInstallCandidateStore(tmp_path / "candidates")
    candidate = _registered_candidate(store)
    store.claim(candidate.candidate_id, expected_sha256=candidate.archive_sha256)
    state = PluginPackageState(manifest=_manifest())
    captured: dict[str, object] = {}

    class _InstallService:
        def __init__(self, **_kwargs):
            pass

        async def install_from_archive(
            self,
            archive_path: Path,
            *,
            approved_manifest,
            approved_package_sha256,
            consented_capabilities,
            progress_reporter,
            admission_lease,
        ):
            captured["archive_bytes"] = archive_path.read_bytes()
            captured["approved_manifest"] = approved_manifest
            captured["approved_package_sha256"] = approved_package_sha256
            captured["capabilities"] = consented_capabilities
            captured["admission_lease"] = admission_lease
            progress_reporter("install", "Installing", 50)
            return state

    monkeypatch.setattr(plugins_install_jobs, "PluginInstallService", _InstallService)
    monkeypatch.setattr(plugins_install_jobs, "_require_plugin_manager", object)
    monkeypatch.setattr(plugins_install_jobs, "_get_registry_client", object)
    monkeypatch.setattr(plugins_install_jobs, "_serialize_package", _package_response)
    job = PluginInstallJob(
        job_id="job-1",
        operation="upload",
        plugin_id="demo-plugin",
        filename="demo.zip",
    )

    await PluginInstallJobManager()._run_candidate_install(job, candidate, store)

    assert captured["archive_bytes"] == b"archive"
    assert captured["approved_manifest"] == candidate.manifest
    assert captured["approved_package_sha256"] == candidate.package_sha256
    assert captured["capabilities"] == candidate.manifest.capabilities
    assert captured["admission_lease"] is None
    assert job.status == "completed"
    with pytest.raises(PluginInstallCandidateNotFoundError):
        store.get(candidate.candidate_id)


@pytest.mark.asyncio
async def test_archive_install_persists_the_approved_capabilities(monkeypatch, tmp_path):
    state = PluginPackageState(manifest=_manifest())
    package_sha256 = _package_sha256()
    captured: dict[str, object] = {}

    class _Manager:
        def get_package(self, _plugin_id):
            return None

        def inspect_plugin_archive(self, archive_path):
            assert archive_path == tmp_path / "demo.zip"
            return PluginArchiveInspection(
                manifest=_manifest(),
                package_sha256=package_sha256,
            )

        def install_plugin_from_archive(
            self,
            archive_path,
            *,
            expected_package_sha256,
            consented_capabilities,
            progress_reporter=None,
        ):
            assert archive_path == tmp_path / "demo.zip"
            assert progress_reporter is None
            captured["expected_package_sha256"] = expected_package_sha256
            captured["consented_capabilities"] = consented_capabilities
            return state

    service = PluginInstallService(
        registry_client=object(),
        plugin_manager=_Manager(),
    )

    result = await service.install_from_archive(
        tmp_path / "demo.zip",
        approved_manifest=state.manifest,
        approved_package_sha256=package_sha256,
        consented_capabilities=state.manifest.capabilities,
    )

    assert result is state
    assert captured["expected_package_sha256"] == package_sha256
    assert captured["consented_capabilities"] == state.manifest.capabilities


@pytest.mark.asyncio
async def test_archive_install_rejects_an_id_installed_after_inspection(tmp_path):
    class _Manager:
        def get_package(self, plugin_id):
            assert plugin_id == "demo-plugin"
            return object()

    service = PluginInstallService(
        registry_client=object(),
        plugin_manager=_Manager(),
    )

    with pytest.raises(PluginSideloadConflictError):
        await service.install_from_archive(
            tmp_path / "demo.zip",
            approved_manifest=_manifest(),
            approved_package_sha256=_package_sha256(),
            consented_capabilities=[],
        )


@pytest.mark.asyncio
async def test_archive_install_rejects_manifest_changed_after_approval(tmp_path):
    changed = _manifest().model_copy(update={"version": "2.0.0"})
    package_sha256 = _package_sha256()

    class _Manager:
        def get_package(self, _plugin_id):
            return None

        def inspect_plugin_archive(self, _archive_path):
            return PluginArchiveInspection(
                manifest=changed,
                package_sha256=package_sha256,
            )

    service = PluginInstallService(
        registry_client=object(),
        plugin_manager=_Manager(),
    )

    with pytest.raises(PluginInstallApprovalMismatchError):
        await service.install_from_archive(
            tmp_path / "demo.zip",
            approved_manifest=_manifest(),
            approved_package_sha256=package_sha256,
            consented_capabilities=[],
        )
