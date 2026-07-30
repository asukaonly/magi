from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from magi.api.routers import plugins_install_jobs
from magi.api.routers.plugins_install_jobs import PluginInstallJob, PluginInstallJobManager
from magi.api.routers.plugins_schemas import PluginManifestResponse, PluginPackageResponse
from magi.plugins.contracts import (
    PluginCapability,
    PluginManifest,
    PluginPackageState,
    PluginPermissions,
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


def _registered_candidate(store: PluginInstallCandidateStore):
    candidate_id, archive_path = store.reserve_archive(".zip")
    archive_path.write_bytes(b"archive")
    return store.register(
        candidate_id=candidate_id,
        archive_path=archive_path,
        original_filename="demo.zip",
        archive_sha256=hashlib.sha256(b"archive").hexdigest(),
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


def test_job_start_claims_candidate_and_rejects_replay(monkeypatch, tmp_path):
    store = PluginInstallCandidateStore(tmp_path / "candidates")
    candidate = _registered_candidate(store)
    manager = PluginInstallJobManager()

    def capture_without_running(_job, install_coro):
        install_coro.close()

    monkeypatch.setattr(
        plugins_install_jobs,
        "get_plugin_install_candidate_store",
        lambda: store,
    )
    monkeypatch.setattr(manager, "_start_task", capture_without_running)

    snapshot = manager.start_candidate_install(
        candidate.candidate_id,
        expected_sha256=candidate.archive_sha256,
    )

    assert snapshot.filename == "demo.zip"
    assert snapshot.plugin_id == "demo-plugin"
    with pytest.raises(PluginInstallCandidateClaimedError):
        manager.start_candidate_install(
            candidate.candidate_id,
            expected_sha256=candidate.archive_sha256,
        )


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
            consented_capabilities,
            progress_reporter,
        ):
            captured["archive_bytes"] = archive_path.read_bytes()
            captured["approved_manifest"] = approved_manifest
            captured["capabilities"] = consented_capabilities
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
    assert captured["capabilities"] == candidate.manifest.capabilities
    assert job.status == "completed"
    with pytest.raises(PluginInstallCandidateNotFoundError):
        store.get(candidate.candidate_id)


@pytest.mark.asyncio
async def test_archive_install_persists_the_approved_capabilities(monkeypatch, tmp_path):
    state = PluginPackageState(manifest=_manifest())
    captured: dict[str, object] = {}

    class _Manager:
        def get_package(self, _plugin_id):
            return None

        def inspect_plugin_archive(self, archive_path):
            assert archive_path == tmp_path / "demo.zip"
            return _manifest()

        def install_plugin_from_archive(
            self,
            archive_path,
            *,
            consented_capabilities,
            progress_reporter=None,
        ):
            assert archive_path == tmp_path / "demo.zip"
            assert progress_reporter is None
            captured["consented_capabilities"] = consented_capabilities
            return state

    service = PluginInstallService(
        registry_client=object(),
        plugin_manager=_Manager(),
    )

    result = await service.install_from_archive(
        tmp_path / "demo.zip",
        approved_manifest=state.manifest,
        consented_capabilities=state.manifest.capabilities,
    )

    assert result is state
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
            consented_capabilities=[],
        )


@pytest.mark.asyncio
async def test_archive_install_rejects_manifest_changed_after_approval(tmp_path):
    changed = _manifest().model_copy(update={"version": "2.0.0"})

    class _Manager:
        def get_package(self, _plugin_id):
            return None

        def inspect_plugin_archive(self, _archive_path):
            return changed

    service = PluginInstallService(
        registry_client=object(),
        plugin_manager=_Manager(),
    )

    with pytest.raises(PluginInstallApprovalMismatchError):
        await service.install_from_archive(
            tmp_path / "demo.zip",
            approved_manifest=_manifest(),
            consented_capabilities=[],
        )
