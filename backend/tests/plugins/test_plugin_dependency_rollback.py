from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import tempfile
import sys
import threading

import pytest

from magi.config.models import AppConfig, PluginSettings
from magi.plugins import install_service as install_service_module
from magi.plugins import package_files
from magi.plugins.contracts import PluginRegistryEntry, PluginRegistryIndex
from magi.plugins.install_service import (
    PluginInstallService,
    _acquire_provisional_dependencies,
)
from magi.plugins.manager import PluginManager
from magi.plugins.package_identity import (
    compute_installed_package_sha256,
    compute_installed_source_sha256,
    compute_package_sha256,
)
from magi.plugins.provisional_dependencies import (
    ProvisionalDependencyConflictError,
    ProvisionalDependencyCoordinator,
    ProvisionalLibraryReceipt,
    ProvisionalLibraryRequirement,
)
from magi.plugins.registry_client import PluginRegistrySnapshot
from magi.plugins.registry_provenance import registry_install_fingerprint
from magi.plugins.sources import SourceRegistry
from runtime_fixtures import instantiate_fixture_plugin
from magi.utils.runtime import RuntimePaths
from magi.tools.registry import ToolRegistry

REGISTRY_URL = "https://example.test/registry.json"
REPO_URL = "https://github.com/example/plugins.git"


def _apply_updates(config: AppConfig, updates: dict[str, object]) -> None:
    for path, value in updates.items():
        current = config
        parts = path.split(".")
        for part in parts[:-1]:
            if hasattr(current, part):
                current = getattr(current, part)
            elif isinstance(current, dict):
                current = current.setdefault(part, {})
            else:  # pragma: no cover - invalid test fixture path
                raise KeyError(part)
        if isinstance(current, dict):
            current[parts[-1]] = value
        else:
            setattr(current, parts[-1], value)


def _patch_config(
    monkeypatch: pytest.MonkeyPatch,
    config: AppConfig,
) -> None:
    config_lock = threading.RLock()

    def save(updates: dict[str, object]) -> bool:
        with config_lock:
            _apply_updates(config, updates)
        return True

    def delete(plugin_id: str) -> bool:
        with config_lock:
            config.plugins.packages.pop(plugin_id, None)
        return True

    monkeypatch.setattr("magi.plugins.manager.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.manager.save_config", save)
    monkeypatch.setattr("magi.plugins.installation.get_config", lambda: config)
    monkeypatch.setattr("magi.plugins.installation.save_config", save)
    monkeypatch.setattr("magi.plugins.installation.delete_plugin_package", delete)
    monkeypatch.setattr("magi.plugins.install_service.get_config", lambda: config)


def _entry(
    plugin_id: str,
    *,
    version: str = "1.0.0",
    kind: str = "plugin",
    depends_on: list[str] | None = None,
    broken: bool = False,
    plugin_source: str | None = None,
) -> PluginRegistryEntry:
    entry = PluginRegistryEntry(
        plugin_id=plugin_id,
        name=plugin_id,
        version=version,
        package_sha256="0" * 64,
        description="Dependency rollback test package",
        author="Test",
        path=plugin_id,
        kind=kind,
        depends_on=depends_on or [],
    )
    return entry.model_copy(
        update={
            "package_sha256": _generated_package_sha256(
                entry,
                broken=broken,
                plugin_source=plugin_source,
            )
        }
    )


def _snapshot(*entries: PluginRegistryEntry) -> PluginRegistrySnapshot:
    index = PluginRegistryIndex(
        plugins=list(entries),
        registry_version="4",
        repo_url=REPO_URL,
    )
    return PluginRegistrySnapshot(
        index=index,
        registry_url=REGISTRY_URL,
        repo_url=REPO_URL,
        install_fingerprint=registry_install_fingerprint(
            index,
            registry_url=REGISTRY_URL,
            repo_url=REPO_URL,
        ),
        official_source=False,
    )


def _write_package(
    dest_root: Path,
    entry: PluginRegistryEntry,
    *,
    broken: bool = False,
) -> Path:
    plugin_dir = dest_root / entry.plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    dependencies = ", ".join(f'"{item}"' for item in entry.depends_on)
    entrypoint = (
        ""
        if entry.kind == "library"
        else '\nentry_module = "plugin"\nentry_class = "RollbackPlugin"'
    )
    (plugin_dir / "plugin.toml").write_text(
        f"""
[plugin]
protocol_version = 2
min_sdk_version = "0.2.0"
execution_mode = "trusted_process"
id = "{entry.plugin_id}"
name = "{entry.name}"
version = "{entry.version}"
description = "{entry.description}"
author = "{entry.author}"
official = false
kind = "{entry.kind}"
contribution_types = []
depends_on = [{dependencies}]
platforms = []{entrypoint}
""".strip(),
        encoding="utf-8",
    )
    if entry.kind == "library":
        (plugin_dir / "__init__.py").write_text("VALUE = 'library'\n", encoding="utf-8")
    elif broken:
        (plugin_dir / "plugin.py").write_text(
            "raise RuntimeError('target commit failed')\n",
            encoding="utf-8",
        )
    else:
        (plugin_dir / "plugin.py").write_text(
            """from magi_plugin_sdk import Plugin


class RollbackPlugin(Plugin):
    pass
""".strip(),
            encoding="utf-8",
        )
    return plugin_dir


def _generated_package_sha256(
    entry: PluginRegistryEntry,
    *,
    broken: bool = False,
    plugin_source: str | None = None,
) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        plugin_dir = _write_package(Path(temp_dir), entry, broken=broken)
        if plugin_source is not None:
            (plugin_dir / "plugin.py").write_text(plugin_source, encoding="utf-8")
        return compute_package_sha256(plugin_dir)


class _Registry:
    def __init__(
        self,
        snapshot: PluginRegistrySnapshot,
        *,
        before_return=None,
        broken_targets: set[str] | None = None,
        plugin_sources: dict[str, str] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.before_return = before_return
        self.broken_targets = broken_targets or set()
        self.plugin_sources = plugin_sources or {}
        self.cloned_plugin_ids: list[str] = []

    async def fetch_snapshot(
        self,
        *,
        force: bool = False,
        deadline_monotonic: float | None = None,
    ) -> PluginRegistrySnapshot:
        return self.snapshot

    async def clone_plugin(
        self,
        entry: PluginRegistryEntry,
        *,
        snapshot: PluginRegistrySnapshot,
        dest_dir: Path | None = None,
        deadline_monotonic: float | None = None,
    ) -> Path:
        assert snapshot is self.snapshot
        assert dest_dir is not None
        self.cloned_plugin_ids.append(entry.plugin_id)
        plugin_dir = _write_package(
            dest_dir,
            entry,
            broken=entry.plugin_id in self.broken_targets,
        )
        plugin_source = self.plugin_sources.get(entry.plugin_id)
        if plugin_source is not None:
            (plugin_dir / "plugin.py").write_text(plugin_source, encoding="utf-8")
        if self.before_return is not None:
            await self.before_return(entry)
        return plugin_dir


def _manager(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[PluginManager, AppConfig, Path]:
    user_root = tmp_path / "user-plugins"
    config = AppConfig()
    _patch_config(monkeypatch, config)
    paths = RuntimePaths(tmp_path / "runtime")
    monkeypatch.setattr("magi.plugins.connections.get_runtime_paths", lambda: paths)
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: user_root)
    return _new_manager(user_root), config, user_root


def _new_manager(user_root: Path) -> PluginManager:
    manager = PluginManager(
        instance_factory=instantiate_fixture_plugin,
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )
    original_outcome = manager._build_directory_install_outcome

    def validate_fixture_commit(plugin_id):
        # Simulate host commit validation failure independently of worker startup.
        state = manager.get_package(plugin_id)
        source = Path(state.manifest.plugin_dir) / "plugin.py"
        if source.is_file() and "target commit failed" in source.read_text():
            raise RuntimeError("target commit failed")

    def validate_outcome(state, **kwargs):
        manager._fixture_commit_check(state.manifest.plugin_id)
        return original_outcome(state, **kwargs)

    manager._fixture_commit_check = validate_fixture_commit
    manager._build_directory_install_outcome = validate_outcome

    return manager


def _service(
    registry: _Registry,
    manager: PluginManager,
    coordinator: ProvisionalDependencyCoordinator,
) -> PluginInstallService:
    return PluginInstallService(
        registry_client=registry,
        plugin_manager=manager,
        provisional_coordinator=coordinator,
    )


def _requirement(
    plugin_id: str,
    *,
    registry_source: str = REGISTRY_URL,
    package_sha256: str = "a" * 64,
) -> ProvisionalLibraryRequirement:
    return ProvisionalLibraryRequirement(
        plugin_id=plugin_id,
        registry_source=registry_source,
        registry_repo_url=REPO_URL,
        package_sha256=package_sha256,
    )


def _receipt(
    requirement: ProvisionalLibraryRequirement,
) -> ProvisionalLibraryReceipt:
    return ProvisionalLibraryReceipt(
        requirement=requirement,
        dependency_package_sha256=(),
        plugin_dir="/tmp/provisional-library",
        manifest_path="/tmp/provisional-library/plugin.toml",
        destination_identity=(1, 2),
        manifest_identity=(1, 2, 3, 4),
    )


@pytest.mark.asyncio
async def test_registry_update_keeps_disabled_plugin_unloaded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plugin_id = "disabled-update-target"
    initial_entry = _entry(plugin_id, version="1.0.0")
    initial_snapshot = _snapshot(initial_entry)
    manager, config, _ = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()

    installed = await _service(
        _Registry(initial_snapshot),
        manager,
        coordinator,
    ).install_from_registry(
        plugin_id,
        expected_fingerprint=initial_snapshot.install_fingerprint,
    )
    assert installed.target_state.loaded is False
    connection = manager.create_connection(plugin_id, display_name="Disabled account", enabled=False)
    assert connection.enabled is False
    assert installed.target_state.trusted is True


    updated_entry = _entry(plugin_id, version="1.1.0")
    updated_snapshot = _snapshot(updated_entry)
    event_loop_thread = threading.get_ident()
    verification_threads: list[int] = []
    original_verification = install_service_module.is_verified_registry_package

    def track_verification(*args, **kwargs) -> bool:
        verification_threads.append(threading.get_ident())
        return original_verification(*args, **kwargs)

    monkeypatch.setattr(
        install_service_module,
        "is_verified_registry_package",
        track_verification,
    )
    updated = await _service(
        _Registry(updated_snapshot),
        manager,
        coordinator,
    ).update_from_registry(
        plugin_id,
        expected_fingerprint=updated_snapshot.install_fingerprint,
    )

    configured = PluginSettings.model_validate(config.plugins.packages[plugin_id])
    assert updated.manifest.version == "1.1.0"
    assert updated.enabled is False
    assert updated.loaded is False
    assert updated.trusted is True
    assert manager.connection_store.get(connection.connection_id).enabled is False
    assert configured.trusted is True
    assert manager.get_connection_plugin(connection.connection_id) is None
    assert verification_threads
    assert event_loop_thread not in verification_threads


@pytest.mark.asyncio
async def test_registry_update_keeps_enabled_plugin_loaded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plugin_id = "enabled-update-target"
    initial_entry = _entry(plugin_id, version="1.0.0")
    initial_snapshot = _snapshot(initial_entry)
    manager, config, _ = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()

    installed = await _service(
        _Registry(initial_snapshot),
        manager,
        coordinator,
    ).install_from_registry(
        plugin_id,
        expected_fingerprint=initial_snapshot.install_fingerprint,
    )
    assert installed.target_state.loaded is False
    connection = manager.create_connection(plugin_id, display_name="Enabled account", enabled=True)
    previous_instance = manager.get_connection_plugin(connection.connection_id)
    assert manager.get_package(plugin_id).loaded is True
    assert previous_instance is not None

    updated_entry = _entry(plugin_id, version="1.1.0")
    updated_snapshot = _snapshot(updated_entry)
    updated = await _service(
        _Registry(updated_snapshot),
        manager,
        coordinator,
    ).update_from_registry(
        plugin_id,
        expected_fingerprint=updated_snapshot.install_fingerprint,
    )

    configured = PluginSettings.model_validate(config.plugins.packages[plugin_id])
    current_instance = manager.get_connection_plugin(connection.connection_id)
    assert updated.manifest.version == "1.1.0"
    assert updated.enabled is True
    assert updated.loaded is True
    assert updated.trusted is True
    assert manager.connection_store.get(connection.connection_id).enabled is True
    assert configured.trusted is True
    assert current_instance is not None
    assert current_instance is not previous_instance


@pytest.mark.parametrize(
    ("registry_source", "package_sha256"),
    [
        ("https://other.example.test/registry.json", "a" * 64),
        (REGISTRY_URL, "b" * 64),
    ],
)
def test_incompatible_claim_fails_atomically_without_partial_claims(
    registry_source: str,
    package_sha256: str,
) -> None:
    coordinator = ProvisionalDependencyCoordinator()
    active_requirement = _requirement("active-library")
    active_lease = coordinator.acquire((active_requirement,))
    unrelated_requirement = _requirement("unrelated-library")
    incompatible_requirement = _requirement(
        active_requirement.plugin_id,
        registry_source=registry_source,
        package_sha256=package_sha256,
    )

    with pytest.raises(ProvisionalDependencyConflictError):
        coordinator.acquire((unrelated_requirement, incompatible_requirement))

    assert coordinator.active_claim_count == 1
    unrelated_lease = coordinator.acquire((unrelated_requirement,))
    assert coordinator.active_claim_count == 2
    unrelated_lease.release()
    active_lease.release()
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_detach_blocks_same_identity_but_finalizer_runs_outside_lock() -> None:
    coordinator = ProvisionalDependencyCoordinator()
    requirement = _requirement("slow-finalizer-library")
    unrelated_requirement = _requirement("unrelated-finalizer-library")
    creator_lease = coordinator.acquire((requirement,))
    detach_entered = threading.Event()
    allow_detach = threading.Event()
    finalizer_entered = threading.Event()
    allow_finalizer = threading.Event()
    same_acquire_started = threading.Event()
    unrelated_acquire_started = threading.Event()

    def detach(_receipt: ProvisionalLibraryReceipt):
        detach_entered.set()
        if not allow_detach.wait(timeout=5):
            raise TimeoutError("detach gate timed out")

        def finalize() -> bool:
            finalizer_entered.set()
            if not allow_finalizer.wait(timeout=5):
                raise TimeoutError("finalizer gate timed out")
            return True

        return finalize

    def acquire_same_identity():
        same_acquire_started.set()
        return coordinator.acquire((requirement,))

    def acquire_unrelated_identity():
        unrelated_acquire_started.set()
        return coordinator.acquire((unrelated_requirement,))

    creator_lease.register_created(_receipt(requirement), detach)
    release_task = asyncio.create_task(asyncio.to_thread(creator_lease.release))
    same_acquire_task = None
    unrelated_acquire_task = None
    heartbeat_stop = asyncio.Event()
    heartbeat_ticks = 0

    async def heartbeat() -> None:
        nonlocal heartbeat_ticks
        while not heartbeat_stop.is_set():
            heartbeat_ticks += 1
            await asyncio.sleep(0)

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        assert await asyncio.to_thread(detach_entered.wait, 5)
        same_acquire_task = asyncio.create_task(asyncio.to_thread(acquire_same_identity))
        unrelated_acquire_task = asyncio.create_task(asyncio.to_thread(acquire_unrelated_identity))
        assert await asyncio.to_thread(same_acquire_started.wait, 5)
        assert await asyncio.to_thread(unrelated_acquire_started.wait, 5)
        await asyncio.sleep(0.02)
        assert not same_acquire_task.done()

        ticks_before_unlock = heartbeat_ticks
        await asyncio.sleep(0.02)
        assert heartbeat_ticks > ticks_before_unlock

        allow_detach.set()
        assert await asyncio.to_thread(finalizer_entered.wait, 5)
        same_lease = await asyncio.wait_for(same_acquire_task, timeout=1)
        unrelated_lease = await asyncio.wait_for(unrelated_acquire_task, timeout=1)
        assert not release_task.done()

        ticks_during_finalizer = heartbeat_ticks
        await asyncio.sleep(0.02)
        assert heartbeat_ticks > ticks_during_finalizer
        await asyncio.to_thread(same_lease.release)
        await asyncio.to_thread(unrelated_lease.release)
    finally:
        allow_detach.set()
        allow_finalizer.set()
        heartbeat_stop.set()
        await heartbeat_task
        if same_acquire_task is not None and not same_acquire_task.done():
            await same_acquire_task
        if unrelated_acquire_task is not None and not unrelated_acquire_task.done():
            await unrelated_acquire_task

    assert await release_task == [requirement.plugin_id]
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_cancelled_waiting_acquire_releases_late_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = ProvisionalDependencyCoordinator()
    blocking_requirement = _requirement("blocking-acquire-library")
    cancelled_requirement = _requirement("cancelled-acquire-library")
    blocking_lease = coordinator.acquire((blocking_requirement,))
    detach_entered = threading.Event()
    allow_detach = threading.Event()
    acquire_started = threading.Event()
    original_acquire = coordinator.acquire

    def detach(_receipt: ProvisionalLibraryReceipt):
        detach_entered.set()
        if not allow_detach.wait(timeout=5):
            raise TimeoutError("acquire contention gate timed out")
        return None

    def track_acquire(requirements):
        acquire_started.set()
        return original_acquire(requirements)

    blocking_lease.register_created(_receipt(blocking_requirement), detach)
    release_task = asyncio.create_task(asyncio.to_thread(blocking_lease.release))
    assert await asyncio.to_thread(detach_entered.wait, 5)
    monkeypatch.setattr(coordinator, "acquire", track_acquire)
    acquire_task = asyncio.create_task(
        _acquire_provisional_dependencies(
            coordinator,
            (cancelled_requirement,),
        )
    )
    assert await asyncio.to_thread(acquire_started.wait, 5)

    acquire_task.cancel()
    allow_detach.set()
    with pytest.raises(asyncio.CancelledError):
        await acquire_task
    await release_task

    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_failed_target_removes_new_provisional_library(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry("rollback-library", kind="library")
    target = _entry("broken-target", depends_on=[library.plugin_id], broken=True)
    snapshot = _snapshot(library, target)
    manager, config, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()

    with pytest.raises(RuntimeError, match="target commit failed"):
        await _service(
            _Registry(snapshot, broken_targets={target.plugin_id}),
            manager,
            coordinator,
        ).install_from_registry(
            target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )

    assert manager.get_package(library.plugin_id) is None
    assert library.plugin_id not in config.plugins.packages
    assert not (user_root / library.plugin_id).exists()
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_identity_capture_failure_rolls_back_published_library(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry("identity-capture-failure-library", kind="library")
    target = _entry("identity-capture-failure-target", depends_on=[library.plugin_id])
    snapshot = _snapshot(library, target)
    manager, config, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()
    original_build_outcome = manager._build_directory_install_outcome

    def fail_library_identity_capture(state, *, created_by_this_commit: bool):
        if state.manifest.plugin_id == library.plugin_id:
            raise RuntimeError("failed to freeze published generation identity")
        return original_build_outcome(
            state,
            created_by_this_commit=created_by_this_commit,
        )

    monkeypatch.setattr(
        manager,
        "_build_directory_install_outcome",
        fail_library_identity_capture,
    )

    with pytest.raises(RuntimeError, match="failed to freeze"):
        await _service(
            _Registry(snapshot),
            manager,
            coordinator,
        ).install_from_registry(
            target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )

    assert manager.get_package(library.plugin_id) is None
    assert library.plugin_id not in config.plugins.packages
    assert not (user_root / library.plugin_id).exists()
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_late_workflow_reinstalls_library_after_prior_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry("release-first-library", kind="library")
    failed_target = _entry(
        "release-first-broken-target",
        depends_on=[library.plugin_id],
        broken=True,
    )
    successful_target = _entry("release-first-success-target", depends_on=[library.plugin_id])
    snapshot = _snapshot(library, failed_target, successful_target)
    manager, _, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()

    with pytest.raises(RuntimeError, match="target commit failed"):
        await _service(
            _Registry(snapshot, broken_targets={failed_target.plugin_id}),
            manager,
            coordinator,
        ).install_from_registry(
            failed_target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )

    assert not (user_root / library.plugin_id).exists()
    second_registry = _Registry(snapshot)
    result = await _service(
        second_registry,
        manager,
        coordinator,
    ).install_from_registry(
        successful_target.plugin_id,
        expected_fingerprint=snapshot.install_fingerprint,
    )

    assert second_registry.cloned_plugin_ids == [
        library.plugin_id,
        successful_target.plugin_id,
    ]
    assert result.extra_installed == [library.plugin_id]
    assert manager.get_package(library.plugin_id) is not None
    assert manager.get_package(successful_target.plugin_id) is not None
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_failed_target_preserves_preexisting_library(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry("existing-library", kind="library")
    target = _entry(
        "broken-existing-target",
        depends_on=[library.plugin_id],
        broken=True,
    )
    snapshot = _snapshot(library, target)
    manager, config, user_root = _manager(monkeypatch, tmp_path)
    source_root = tmp_path / "preexisting"
    library_dir = _write_package(source_root, library)
    package_sha256 = compute_package_sha256(library_dir)
    assert package_sha256 == library.package_sha256
    manager.install_plugin_from_directory(
        library_dir,
        install_origin="registry",
        registry_source=REGISTRY_URL,
        registry_repo_url=REPO_URL,
        package_sha256=package_sha256,
        dependency_package_sha256={},
    )
    configured_library = PluginSettings.model_validate(config.plugins.packages[library.plugin_id])
    assert configured_library.package_sha256 == package_sha256
    assert configured_library.installed_package_sha256 == (
        compute_installed_package_sha256(user_root / library.plugin_id)
    )
    coordinator = ProvisionalDependencyCoordinator()

    with pytest.raises(RuntimeError, match="target commit failed"):
        await _service(
            _Registry(snapshot, broken_targets={target.plugin_id}),
            manager,
            coordinator,
        ).install_from_registry(
            target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )

    assert manager.get_package(library.plugin_id) is not None
    assert library.plugin_id in config.plugins.packages
    assert (user_root / library.plugin_id / "plugin.toml").is_file()
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_failed_and_successful_workflows_share_library_without_deletion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry("shared-rollback-library", kind="library")
    failed_target = _entry(
        "failed-shared-target",
        depends_on=[library.plugin_id],
        broken=True,
    )
    successful_target = _entry("successful-shared-target", depends_on=[library.plugin_id])
    snapshot = _snapshot(library, failed_target, successful_target)
    successful_target_waiting = asyncio.Event()
    allow_successful_target = asyncio.Event()

    async def before_return(entry: PluginRegistryEntry) -> None:
        if entry.plugin_id == successful_target.plugin_id:
            successful_target_waiting.set()
            await allow_successful_target.wait()
        elif entry.plugin_id == failed_target.plugin_id:
            await successful_target_waiting.wait()

    manager, _, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()
    service = _service(
        _Registry(
            snapshot,
            before_return=before_return,
            broken_targets={failed_target.plugin_id},
        ),
        manager,
        coordinator,
    )
    failed = asyncio.create_task(
        service.install_from_registry(
            failed_target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )
    )
    successful = asyncio.create_task(
        service.install_from_registry(
            successful_target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )
    )

    with pytest.raises(RuntimeError, match="target commit failed"):
        await failed
    assert (user_root / library.plugin_id / "plugin.toml").is_file()

    allow_successful_target.set()
    result = await successful

    assert result.target_state.manifest.plugin_id == successful_target.plugin_id
    assert manager.get_package(library.plugin_id) is not None
    assert manager.get_package(successful_target.plugin_id) is not None
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_late_workflow_claims_published_library_before_first_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry("late-claim-library", kind="library")
    failed_target = _entry(
        "late-claim-broken-target",
        depends_on=[library.plugin_id],
        broken=True,
    )
    successful_target = _entry("late-claim-success-target", depends_on=[library.plugin_id])
    snapshot = _snapshot(library, failed_target, successful_target)
    manager, _, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()
    library_published = threading.Event()
    second_workflow_claimed = threading.Event()
    allow_second_target = asyncio.Event()
    original_install = manager.install_plugin_from_directory

    def coordinate_target_installs(plugin_dir: Path, **kwargs):
        if plugin_dir.name == failed_target.plugin_id:
            if not second_workflow_claimed.wait(timeout=5):
                raise TimeoutError("second workflow did not claim the published library")
        state = original_install(plugin_dir, **kwargs)
        if plugin_dir.name == library.plugin_id:
            library_published.set()
        return state

    async def hold_second_target(entry: PluginRegistryEntry) -> None:
        if entry.plugin_id == successful_target.plugin_id:
            second_workflow_claimed.set()
            await allow_second_target.wait()

    monkeypatch.setattr(
        manager,
        "install_plugin_from_directory",
        coordinate_target_installs,
    )
    first_registry = _Registry(
        snapshot,
        broken_targets={failed_target.plugin_id},
    )
    first_task = asyncio.create_task(
        _service(
            first_registry,
            manager,
            coordinator,
        ).install_from_registry(
            failed_target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )
    )
    assert await asyncio.to_thread(library_published.wait, 5)

    second_registry = _Registry(snapshot, before_return=hold_second_target)
    second_task = asyncio.create_task(
        _service(
            second_registry,
            manager,
            coordinator,
        ).install_from_registry(
            successful_target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )
    )

    with pytest.raises(RuntimeError, match="target commit failed"):
        await first_task
    assert second_registry.cloned_plugin_ids == [successful_target.plugin_id]
    assert (user_root / library.plugin_id / "plugin.toml").is_file()

    allow_second_target.set()
    result = await second_task

    assert result.extra_installed == []
    assert manager.get_package(library.plugin_id) is not None
    assert manager.get_package(successful_target.plugin_id) is not None
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_creator_manager_cleans_when_stale_manager_releases_last(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry("creator-owned-library", kind="library")
    creator_target = _entry(
        "creator-owned-broken-target",
        depends_on=[library.plugin_id],
        broken=True,
    )
    stale_target = _entry("stale-manager-target", depends_on=[library.plugin_id])
    snapshot = _snapshot(library, creator_target, stale_target)
    creator_manager, config, user_root = _manager(monkeypatch, tmp_path)
    stale_manager = _new_manager(user_root)
    coordinator = ProvisionalDependencyCoordinator()
    library_published = threading.Event()
    stale_workflow_claimed = threading.Event()
    hold_stale_clone = asyncio.Event()
    original_install = creator_manager.install_plugin_from_directory

    def coordinate_creator_target(plugin_dir: Path, **kwargs):
        if plugin_dir.name == creator_target.plugin_id:
            if not stale_workflow_claimed.wait(timeout=5):
                raise TimeoutError("stale manager workflow did not acquire its claim")
        state = original_install(plugin_dir, **kwargs)
        if plugin_dir.name == library.plugin_id:
            library_published.set()
        return state

    async def hold_stale_library_clone(entry: PluginRegistryEntry) -> None:
        if entry.plugin_id == library.plugin_id:
            stale_workflow_claimed.set()
            await hold_stale_clone.wait()

    monkeypatch.setattr(
        creator_manager,
        "install_plugin_from_directory",
        coordinate_creator_target,
    )
    creator_task = asyncio.create_task(
        _service(
            _Registry(snapshot, broken_targets={creator_target.plugin_id}),
            creator_manager,
            coordinator,
        ).install_from_registry(
            creator_target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )
    )
    assert await asyncio.to_thread(library_published.wait, 5)
    assert stale_manager.installed_plugin_ids() == set()

    stale_task = asyncio.create_task(
        _service(
            _Registry(snapshot, before_return=hold_stale_library_clone),
            stale_manager,
            coordinator,
        ).install_from_registry(
            stale_target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )
    )

    with pytest.raises(RuntimeError, match="target commit failed"):
        await creator_task
    assert (user_root / library.plugin_id / "plugin.toml").is_file()

    stale_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stale_task

    assert creator_manager.get_package(library.plugin_id) is None
    assert stale_manager.get_package(library.plugin_id) is None
    assert library.plugin_id not in config.plugins.packages
    assert not (user_root / library.plugin_id).exists()
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_two_failed_workflows_remove_shared_library_after_last_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry("all-failed-library", kind="library")
    first_target = _entry(
        "first-broken-target",
        depends_on=[library.plugin_id],
        broken=True,
    )
    second_target = _entry(
        "second-broken-target",
        depends_on=[library.plugin_id],
        broken=True,
    )
    snapshot = _snapshot(library, first_target, second_target)
    targets_ready = asyncio.Event()
    target_count = 0

    async def before_return(entry: PluginRegistryEntry) -> None:
        nonlocal target_count
        if entry.kind != "plugin":
            return
        target_count += 1
        if target_count == 2:
            targets_ready.set()
        await targets_ready.wait()

    manager, config, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()
    service = _service(
        _Registry(
            snapshot,
            before_return=before_return,
            broken_targets={first_target.plugin_id, second_target.plugin_id},
        ),
        manager,
        coordinator,
    )

    results = await asyncio.gather(
        service.install_from_registry(
            first_target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        ),
        service.install_from_registry(
            second_target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        ),
        return_exceptions=True,
    )

    assert all(isinstance(result, RuntimeError) for result in results)
    assert manager.get_package(library.plugin_id) is None
    assert library.plugin_id not in config.plugins.packages
    assert not (user_root / library.plugin_id).exists()
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_nested_libraries_are_removed_in_reverse_dependency_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    leaf = _entry("rollback-leaf", kind="library")
    parent = _entry("rollback-parent", kind="library", depends_on=[leaf.plugin_id])
    target = _entry(
        "broken-nested-target",
        depends_on=[parent.plugin_id],
        broken=True,
    )
    snapshot = _snapshot(leaf, parent, target)
    manager, config, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()

    with pytest.raises(RuntimeError, match="target commit failed"):
        await _service(
            _Registry(snapshot, broken_targets={target.plugin_id}),
            manager,
            coordinator,
        ).install_from_registry(
            target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )

    assert manager.get_package(parent.plugin_id) is None
    assert manager.get_package(leaf.plugin_id) is None
    assert parent.plugin_id not in config.plugins.packages
    assert leaf.plugin_id not in config.plugins.packages
    assert not (user_root / parent.plugin_id).exists()
    assert not (user_root / leaf.plugin_id).exists()
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_nested_library_owned_by_stale_manager_preserves_retained_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    leaf = _entry("cross-owner-leaf", kind="library")
    parent = _entry("cross-owner-parent", kind="library", depends_on=[leaf.plugin_id])
    leaf_target = _entry(
        "cross-owner-leaf-target",
        depends_on=[leaf.plugin_id],
        broken=True,
    )
    parent_target = _entry(
        "cross-owner-parent-target",
        depends_on=[parent.plugin_id],
        broken=True,
    )
    snapshot = _snapshot(leaf, parent, leaf_target, parent_target)
    leaf_manager, config, user_root = _manager(monkeypatch, tmp_path)
    parent_manager = _new_manager(user_root)
    coordinator = ProvisionalDependencyCoordinator()
    leaf_published = threading.Event()
    allow_leaf_target_failure = threading.Event()
    original_leaf_install = leaf_manager.install_plugin_from_directory

    def hold_leaf_target(plugin_dir: Path, **kwargs):
        if plugin_dir.name == leaf_target.plugin_id:
            if not allow_leaf_target_failure.wait(timeout=5):
                raise TimeoutError("parent workflow did not finish before leaf target")
        state = original_leaf_install(plugin_dir, **kwargs)
        if plugin_dir.name == leaf.plugin_id:
            leaf_published.set()
        return state

    monkeypatch.setattr(
        leaf_manager,
        "install_plugin_from_directory",
        hold_leaf_target,
    )
    leaf_task = asyncio.create_task(
        _service(
            _Registry(snapshot, broken_targets={leaf_target.plugin_id}),
            leaf_manager,
            coordinator,
        ).install_from_registry(
            leaf_target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )
    )
    assert await asyncio.to_thread(leaf_published.wait, 5)
    parent_manager.scan(persist_discovery=False)
    assert parent_manager.get_package(leaf.plugin_id) is not None

    original_parent_load = parent_manager._fixture_commit_check
    parent_generation_replaced = False

    def retain_parent_then_fail(plugin_id: str):
        nonlocal parent_generation_replaced
        if plugin_id == parent_target.plugin_id:
            parent_dir = user_root / parent.plugin_id
            replacement_dir = tmp_path / "cross-owner-parent-replacement"
            displaced_dir = tmp_path / "cross-owner-parent-displaced"
            shutil.copytree(parent_dir, replacement_dir)
            parent_dir.replace(displaced_dir)
            replacement_dir.replace(parent_dir)
            parent_generation_replaced = True
        return original_parent_load(plugin_id)

    monkeypatch.setattr(parent_manager, "_fixture_commit_check", retain_parent_then_fail)
    try:
        with pytest.raises(RuntimeError, match="target commit failed"):
            await _service(
                _Registry(snapshot, broken_targets={parent_target.plugin_id}),
                parent_manager,
                coordinator,
            ).install_from_registry(
                parent_target.plugin_id,
                expected_fingerprint=snapshot.install_fingerprint,
            )
    finally:
        allow_leaf_target_failure.set()

    assert parent_generation_replaced
    assert (user_root / parent.plugin_id / "plugin.toml").is_file()
    assert (user_root / leaf.plugin_id / "plugin.toml").is_file()

    with pytest.raises(RuntimeError, match="target commit failed"):
        await leaf_task

    assert parent.plugin_id in config.plugins.packages
    assert leaf.plugin_id in config.plugins.packages
    assert parent_manager.get_package(parent.plugin_id) is not None
    assert leaf_manager.get_package(leaf.plugin_id) is not None
    assert (user_root / parent.plugin_id / "plugin.toml").is_file()
    assert (user_root / leaf.plugin_id / "plugin.toml").is_file()
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_identity_change_prevents_provisional_library_deletion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry("changed-identity-library", kind="library")
    target = _entry("identity-changing-target", depends_on=[library.plugin_id])
    snapshot = _snapshot(library, target)
    manager, config, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()
    original_load = manager._fixture_commit_check

    def mutate_identity_then_fail(plugin_id: str):
        if plugin_id == target.plugin_id:
            package_config = config.plugins.packages[library.plugin_id]
            if isinstance(package_config, dict):
                package_config["package_sha256"] = "f" * 64
            else:
                package_config.package_sha256 = "f" * 64
            raise RuntimeError("identity changed before rollback")
        return original_load(plugin_id)

    monkeypatch.setattr(manager, "_fixture_commit_check", mutate_identity_then_fail)

    with pytest.raises(RuntimeError, match="identity changed"):
        await _service(
            _Registry(snapshot),
            manager,
            coordinator,
        ).install_from_registry(
            target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )

    assert manager.get_package(library.plugin_id) is not None
    assert library.plugin_id in config.plugins.packages
    assert (user_root / library.plugin_id / "plugin.toml").is_file()
    assert coordinator.active_claim_count == 0


@pytest.mark.parametrize("replaced_path", ["directory", "manifest"])
@pytest.mark.asyncio
async def test_managed_path_replacement_prevents_provisional_library_deletion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    replaced_path: str,
) -> None:
    library = _entry(f"replaced-{replaced_path}-library", kind="library")
    target = _entry(
        f"{replaced_path}-replacement-target",
        depends_on=[library.plugin_id],
    )
    snapshot = _snapshot(library, target)
    manager, config, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()
    original_load = manager._fixture_commit_check

    def replace_managed_path_then_fail(plugin_id: str):
        if plugin_id == target.plugin_id:
            library_dir = user_root / library.plugin_id
            if replaced_path == "directory":
                replacement_dir = tmp_path / "replacement-library"
                displaced_dir = tmp_path / "displaced-library"
                shutil.copytree(library_dir, replacement_dir)
                library_dir.replace(displaced_dir)
                replacement_dir.replace(library_dir)
            else:
                manifest_path = library_dir / "plugin.toml"
                replacement_manifest = tmp_path / "replacement-plugin.toml"
                replacement_manifest.write_bytes(manifest_path.read_bytes())
                replacement_manifest.replace(manifest_path)
            raise RuntimeError("managed path identity changed before rollback")
        return original_load(plugin_id)

    monkeypatch.setattr(manager, "_fixture_commit_check", replace_managed_path_then_fail)

    with pytest.raises(RuntimeError, match="managed path identity changed"):
        await _service(
            _Registry(snapshot),
            manager,
            coordinator,
        ).install_from_registry(
            target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )

    assert manager.get_package(library.plugin_id) is not None
    assert library.plugin_id in config.plugins.packages
    assert (user_root / library.plugin_id / "plugin.toml").is_file()
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_generation_replaced_before_receipt_registration_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry("pre-receipt-replacement-library", kind="library")
    target = _entry(
        "pre-receipt-replacement-target",
        depends_on=[library.plugin_id],
        broken=True,
    )
    snapshot = _snapshot(library, target)
    manager, config, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()
    original_replace = manager._replace_plugin_package
    replacement_completed = False

    def replace_generation_after_commit(plan, *args, **kwargs):
        nonlocal replacement_completed
        outcome = original_replace(plan, *args, **kwargs)
        if plan.plugin_id == library.plugin_id:
            library_dir = user_root / library.plugin_id
            replacement_dir = tmp_path / "pre-receipt-replacement"
            displaced_dir = tmp_path / "pre-receipt-displaced"
            shutil.copytree(library_dir, replacement_dir)
            library_dir.replace(displaced_dir)
            replacement_dir.replace(library_dir)
            replacement_completed = True
        return outcome

    monkeypatch.setattr(
        manager,
        "_replace_plugin_package",
        replace_generation_after_commit,
    )

    with pytest.raises(RuntimeError, match="target commit failed"):
        await _service(
            _Registry(snapshot, broken_targets={target.plugin_id}),
            manager,
            coordinator,
        ).install_from_registry(
            target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )

    assert replacement_completed
    assert manager.get_package(library.plugin_id) is not None
    assert library.plugin_id in config.plugins.packages
    assert (user_root / library.plugin_id / "plugin.toml").is_file()
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_new_consumer_prevents_provisional_library_deletion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry("new-consumer-library", kind="library")
    target = _entry(
        "new-consumer-broken-target",
        depends_on=[library.plugin_id],
        broken=True,
    )
    consumer = _entry("late-installed-consumer", depends_on=[library.plugin_id])
    snapshot = _snapshot(library, target, consumer)
    manager, config, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()
    consumer_dir = _write_package(tmp_path / "consumer-source", consumer)
    consumer_package_sha256 = compute_package_sha256(consumer_dir)
    assert consumer_package_sha256 == consumer.package_sha256
    original_install = manager.install_plugin_from_directory

    def install_consumer_before_target(plugin_dir: Path, **kwargs):
        if plugin_dir.name == target.plugin_id:
            library_package_sha256 = compute_installed_source_sha256(user_root / library.plugin_id)
            assert library_package_sha256 == library.package_sha256
            original_install(
                consumer_dir,
                install_origin="registry",
                registry_source=REGISTRY_URL,
                registry_repo_url=REPO_URL,
                package_sha256=consumer_package_sha256,
                dependency_package_sha256={library.plugin_id: library_package_sha256},
            )
        return original_install(plugin_dir, **kwargs)

    monkeypatch.setattr(
        manager,
        "install_plugin_from_directory",
        install_consumer_before_target,
    )

    with pytest.raises(RuntimeError, match="target commit failed"):
        await _service(
            _Registry(snapshot, broken_targets={target.plugin_id}),
            manager,
            coordinator,
        ).install_from_registry(
            target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )

    assert manager.get_package(library.plugin_id) is not None
    assert manager.get_package(consumer.plugin_id) is not None
    assert library.plugin_id in config.plugins.packages
    assert consumer.plugin_id in config.plugins.packages
    assert (user_root / library.plugin_id / "plugin.toml").is_file()
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_package_install_does_not_import_dependency_before_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    library = _entry("runtime_cache_library", kind="library")
    target_source = f"import {library.plugin_id}\nraise RuntimeError('failed after dependency import')\n"
    target = _entry("runtime-cache-target", depends_on=[library.plugin_id], plugin_source=target_source)
    snapshot = _snapshot(library, target)
    manager, config, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()

    installed = await _service(
        _Registry(snapshot, plugin_sources={target.plugin_id: target_source}), manager, coordinator,
    ).install_from_registry(target.plugin_id, expected_fingerprint=snapshot.install_fingerprint)

    assert installed.target_state.loaded is False
    assert manager.connection_store.list(target.plugin_id) == []
    assert library.plugin_id not in sys.modules
    assert not (user_root / library.plugin_id / "__pycache__").exists()
    assert (user_root / library.plugin_id).is_dir()
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_cancellation_during_library_commit_waits_and_cleans(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry("commit-cancelled-library", kind="library")
    target = _entry("commit-cancelled-target", depends_on=[library.plugin_id])
    snapshot = _snapshot(library, target)
    manager, config, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()
    original_commit = manager._commit_staged_plugin_package
    library_commit_entered = threading.Event()
    release_library_commit = threading.Event()

    def block_library_commit(plan, *args, **kwargs):
        if plan.plugin_id == library.plugin_id:
            library_commit_entered.set()
            if not release_library_commit.wait(timeout=5):
                raise TimeoutError("library commit test gate timed out")
        return original_commit(plan, *args, **kwargs)

    monkeypatch.setattr(
        manager,
        "_commit_staged_plugin_package",
        block_library_commit,
    )
    install_task = asyncio.create_task(
        _service(
            _Registry(snapshot),
            manager,
            coordinator,
        ).install_from_registry(
            target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )
    )

    assert await asyncio.to_thread(library_commit_entered.wait, 5)
    install_task.cancel()
    release_library_commit.set()
    with pytest.raises(asyncio.CancelledError):
        await install_task

    assert manager.get_package(library.plugin_id) is None
    assert library.plugin_id not in config.plugins.packages
    assert not (user_root / library.plugin_id).exists()
    assert coordinator.active_claim_count == 0


@pytest.mark.asyncio
async def test_cancellation_waits_for_commit_then_cleans_provisional_library(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry("cancelled-library", kind="library")
    target = _entry("cancelled-target", depends_on=[library.plugin_id])
    snapshot = _snapshot(library, target)
    manager, config, user_root = _manager(monkeypatch, tmp_path)
    coordinator = ProvisionalDependencyCoordinator()
    original_install = manager.install_plugin_from_directory
    target_entered = threading.Event()
    release_target = threading.Event()

    def block_target(plugin_dir: Path, **kwargs):
        if plugin_dir.name == target.plugin_id:
            target_entered.set()
            release_target.wait(timeout=5)
            raise RuntimeError("cancelled target stopped before commit")
        return original_install(plugin_dir, **kwargs)

    monkeypatch.setattr(manager, "install_plugin_from_directory", block_target)
    install_task = asyncio.create_task(
        _service(
            _Registry(snapshot),
            manager,
            coordinator,
        ).install_from_registry(
            target.plugin_id,
            expected_fingerprint=snapshot.install_fingerprint,
        )
    )

    assert await asyncio.to_thread(target_entered.wait, 5)
    install_task.cancel()
    release_target.set()
    with pytest.raises(asyncio.CancelledError):
        await install_task

    assert manager.get_package(library.plugin_id) is None
    assert library.plugin_id not in config.plugins.packages
    assert not (user_root / library.plugin_id).exists()
    assert coordinator.active_claim_count == 0
