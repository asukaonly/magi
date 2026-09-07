"""Installed graph upgrades preserve exact consent, packages and connections."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from magi_plugin_sdk import Plugin

from magi.config.models import AppConfig, PluginSettings
from magi.plugins import installation, package_files
from magi.plugins.connections import PluginConnectionStore
from magi.plugins.install_service import (
    PluginDependencyConflictError,
    PluginInstallApprovalMismatchError,
    PluginInstallService,
    PluginRegistryVersionError,
)
from magi.plugins.manager import PluginManager
from magi.plugins.package_identity import compute_installed_package_sha256
from magi.plugins.package_identity import compute_package_sha256
from magi.plugins.package_identity import purge_plugin_bytecode_caches
from magi.plugins.package_integrity import package_identity_error
from magi.plugins.sources import SourceRegistry
from magi.tools.registry import ToolRegistry
from magi.utils.runtime import RuntimePaths
from test_plugin_dependency_install_concurrency import (
    _apply_updates,
    _entry as base_entry,
    _patch_config,
    _snapshot,
    _write_package as write_base_package,
)

LIBRARY_ID = "shared_library"


def installed_digest(directory):
    purge_plugin_bytecode_caches(directory)
    return compute_installed_package_sha256(directory)


def _write_package(root, entry):
    path = write_base_package(root, entry)
    if entry.kind == "plugin":
        with (path / "plugin.toml").open("a") as stream:
            stream.write(
                '\n[[plugin.settings_resources]]\nresource_name = "login"\nrequires_enabled = false\n'
            )
        (path / "plugin.py").write_text("""import os
from magi_plugin_sdk import Plugin
from shared_library import VERSION

class ConcurrentPlugin(Plugin):
    def read_settings_resource(self, resource_name):
        return {"version": VERSION, "pid": os.getpid()}
""")
    else:
        (path / "shared_value.py").write_text(f'VERSION = "{entry.version}"\n')
    return path


def _entry(plugin_id, **kwargs):
    import tempfile

    entry = base_entry(plugin_id, **kwargs)
    with tempfile.TemporaryDirectory() as root:
        return entry.model_copy(
            update={"package_sha256": compute_package_sha256(_write_package(Path(root), entry))}
        )


class Registry:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.downloaded = []
        self.fail_download = None
        self.after_download = None

    async def fetch_snapshot(self, **kwargs):
        return self.snapshot

    async def clone_plugin(self, entry, *, snapshot, dest_dir, **kwargs):
        assert snapshot is self.snapshot
        self.downloaded.append(entry.plugin_id)
        if entry.plugin_id == self.fail_download:
            raise RuntimeError("injected download failure")
        path = _write_package(dest_dir, entry)
        if self.after_download is not None:
            self.after_download(entry, path)
        return path


@pytest.fixture
async def runtime(monkeypatch, tmp_path, request):
    config = AppConfig()
    _patch_config(monkeypatch, config)

    def save(updates):
        _apply_updates(config, updates)
        config.plugins.packages = {
            key: PluginSettings.model_validate(value)
            for key, value in config.plugins.packages.items()
        }
        return True

    monkeypatch.setattr(installation, "save_config", save)
    monkeypatch.setattr("magi.plugins.manager.save_config", save)
    root = tmp_path / "plugins"
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: root)
    events = []
    failures = set()
    running = set()
    store = PluginConnectionStore(
        runtime_paths=RuntimePaths(base_dir=tmp_path / "runtime"),
        require_package=lambda key: manager._require_connection_package(key),
        authorize_enable=lambda connection: manager._authorize_connection(connection),
        validate_settings=lambda _: None,
    )

    class Instance(Plugin):
        async def shutdown(self):
            # Yield to the host loop and reenter the manager lock. Publication
            # must wait, without holding that lock across shutdown callbacks.
            await asyncio.sleep(0)
            state = manager.get_package(self.plugin_id)
            assert state.manifest.version == self.manifest.version
            assert (
                root / LIBRARY_ID / "__init__.py"
            ).read_text().strip() == f'VERSION = "{self.library_version}"'
            events.append(("stop", self.plugin_id, self.manifest.version))
            running.discard(self.connection_id)

    def factory(manifest, connection, context):
        failure = (manifest.plugin_id, manifest.version)
        if failure in failures:
            failures.remove(failure)
            raise RuntimeError("injected reload failure")
        assert connection.connection_id not in running
        manager._capture_plugin_dependencies(
            manifest,
            registry_source=REGISTRY_URL,
            registry_repo_url=REPO_URL,
            dependency_package_sha256=PluginSettings.model_validate(
                config.plugins.packages[manifest.plugin_id]
            ).dependency_package_sha256,
        )
        instance = Instance()
        instance.configure(manifest=manifest, connection=connection, context=context)
        instance.library_version = manager.get_package(LIBRARY_ID).manifest.version
        running.add(connection.connection_id)
        events.append(("start", manifest.plugin_id, manifest.version))
        return instance

    manager = PluginManager(
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        search_paths=[root],
        request_source_schedule_refresh=lambda: None,
        connection_store=store,
        instance_factory=None if getattr(request, "param", None) == "workers" else factory,
    )
    old = [
        _entry(LIBRARY_ID, kind="library"),
        _entry("consumer-a", depends_on=[LIBRARY_ID]),
        _entry("consumer-b", depends_on=[LIBRARY_ID]),
    ]
    registry = Registry(_snapshot(*old))
    service = PluginInstallService(registry_client=registry, plugin_manager=manager)
    for key in ("consumer-a", "consumer-b"):
        await service.install_from_registry(
            key, expected_fingerprint=service._build_registry_install_plan(key, snapshot=registry.snapshot, update=False).fingerprint
        )
    connections = [
        manager.create_connection(
            key,
            display_name=f"Account {key}",
            settings={"folder": f"/chosen/{key}"},
            credentials={"token": f"secret-{key}"},
            enabled=True,
        )
        for key in ("consumer-a", "consumer-b")
    ]
    disabled = manager.create_connection(
        "consumer-b", display_name="Disabled", settings={"folder": "/disabled"}
    )
    new = [item.model_copy(update={"version": "2.0.0"}) for item in old]
    new = [
        _entry(item.plugin_id, kind=item.kind, version=item.version, depends_on=item.depends_on)
        for item in new
    ]
    registry.snapshot = _snapshot(*new)
    registry.downloaded.clear()
    events.clear()
    before_config = {
        key: PluginSettings.model_validate(value).model_dump(mode="json")
        for key, value in config.plugins.packages.items()
    }
    before_connections = [item.model_dump(mode="json") for item in store.list()]
    before_hashes = {key: installed_digest(root / key) for key in before_config}
    result = SimpleNamespace(
        config=config,
        root=root,
        manager=manager,
        registry=registry,
        service=service,
        events=events,
        failures=failures,
        running=running,
        store=store,
        connections=connections,
        disabled=disabled,
        old=old,
        new=new,
        before_config=before_config,
        before_connections=before_connections,
        before_hashes=before_hashes,
    )
    yield result
    await manager.shutdown()


REGISTRY_URL = "https://example.test/registry.json"
REPO_URL = "https://github.com/example/plugins.git"


def assert_connections_preserved(runtime):
    assert [
        item.model_dump(mode="json") for item in runtime.store.list()
    ] == runtime.before_connections
    for connection in runtime.connections:
        assert (
            runtime.store.context(connection.connection_id).credentials.get("token")
            == f"secret-{connection.plugin_id}"
        )
        assert connection.connection_id in runtime.running
    assert (runtime.disabled.connection_id in runtime.running) == (
        runtime.disabled.connection_id in runtime.manager._setup_instances
    )


def assert_restored(runtime):
    assert {
        key: PluginSettings.model_validate(value).model_dump(mode="json")
        for key, value in runtime.config.plugins.packages.items()
    } == runtime.before_config
    assert {
        key: installed_digest(runtime.root / key) for key in runtime.before_hashes
    } == runtime.before_hashes
    assert set(runtime.manager.installed_plugin_ids()) == set(runtime.before_config)
    for key in runtime.before_hashes:
        assert runtime.manager.get_package(key).manifest.version == "1.0.0"
    assert_connections_preserved(runtime)


@pytest.mark.asyncio
async def test_two_consumers_upgrade_only_with_complete_reviewed_plan(runtime):
    plan = await runtime.service.plan_registry_install("consumer-a", update=True)
    displayed = plan.to_dict()
    assert displayed["coordinated"] is True
    assert plan.fingerprint != runtime.registry.snapshot.install_fingerprint
    assert [item.entry.plugin_id for item in plan.changes] == [
        LIBRARY_ID,
        "consumer-a",
        "consumer-b",
    ]
    assert all(
        item.action == "update"
        and item.current_version == "1.0.0"
        and item.entry.version == "2.0.0"
        for item in plan.changes
    )
    assert plan.changes[-1].reason == f"consumer of {LIBRARY_ID}"
    for item in plan.changes:
        assert (
            item.current_package_sha256
            == runtime.before_config[item.entry.plugin_id]["package_sha256"]
        )
        assert item.current_installed_package_sha256 == runtime.before_hashes[item.entry.plugin_id]
    with pytest.raises(PluginInstallApprovalMismatchError):
        await runtime.service.update_from_registry(
            "consumer-a", expected_fingerprint=runtime.registry.snapshot.install_fingerprint
        )
    assert runtime.registry.downloaded == []
    state = await runtime.service.update_from_registry(
        "consumer-a", expected_fingerprint=plan.fingerprint
    )
    assert state.manifest.version == "2.0.0"
    assert {item.manifest.version for item in runtime.manager.list_packages()} == {"2.0.0"}
    assert runtime.events[:2] == [("stop", "consumer-b", "1.0.0"), ("stop", "consumer-a", "1.0.0")]
    assert {item for item in runtime.events[2:]} == {
        ("start", "consumer-a", "2.0.0"),
        ("start", "consumer-b", "2.0.0"),
    }
    for item in runtime.new:
        record = PluginSettings.model_validate(runtime.config.plugins.packages[item.plugin_id])
        assert record.package_sha256 == item.package_sha256
        assert (
            package_identity_error(runtime.manager.get_package(item.plugin_id).manifest, record)
            is None
        )
        if item.kind == "plugin":
            assert record.dependency_package_sha256 == {LIBRARY_ID: runtime.new[0].package_sha256}
    assert_connections_preserved(runtime)
    assert list(runtime.root.parent.glob(".plugins-*-backup-*")) == []
    with pytest.raises(ValueError, match="still required"):
        runtime.manager.uninstall_plugin(LIBRARY_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["download", "stage", "swap", "save", "scan", "reload", "setup"]
)
async def test_failure_restores_entire_old_closure(runtime, monkeypatch, failure):
    plan = await runtime.service.plan_registry_install("consumer-a", update=True)
    if failure == "download":
        runtime.registry.fail_download = "consumer-b"
    elif failure == "stage":
        original = runtime.manager._install_staged_dependencies

        def fail_stage(path, **kwargs):
            original(path, **kwargs)
            if "consumer-b" in path.name:
                raise RuntimeError("injected stage failure")

        monkeypatch.setattr(runtime.manager, "_install_staged_dependencies", fail_stage)
    elif failure == "swap":
        original = package_files.promote_staged_plugin_directory

        def fail_swap(staged, destination, **kwargs):
            if destination.name == "consumer-b":
                raise RuntimeError("injected swap failure")
            return original(staged, destination, **kwargs)

        monkeypatch.setattr(package_files, "promote_staged_plugin_directory", fail_swap)
    elif failure == "save":
        failed = False

        def fail_save(updates):
            nonlocal failed
            _apply_updates(runtime.config, updates)
            if not failed:
                failed = True
                return False
            return True

        monkeypatch.setattr(installation, "save_config", fail_save)
    elif failure == "scan":
        original = runtime.manager.scan
        failed = False

        def fail_scan(**kwargs):
            nonlocal failed
            result = original(**kwargs)
            if not failed:
                failed = True
                raise RuntimeError("injected scan failure")
            return result

        monkeypatch.setattr(runtime.manager, "scan", fail_scan)
    elif failure == "setup":
        runtime.manager.setup_connection(runtime.disabled.connection_id)
        runtime.failures.add(("consumer-b", "2.0.0"))
    else:
        runtime.failures.add(("consumer-b", "2.0.0"))
    with pytest.raises(RuntimeError):
        await runtime.service.update_from_registry(
            "consumer-a", expected_fingerprint=plan.fingerprint
        )
    if failure == "setup":
        assert runtime.disabled.connection_id in runtime.manager._setup_instances
    assert_restored(runtime)


@pytest.mark.asyncio
async def test_missing_new_consumer_release_blocks_without_touching_packages(runtime):
    runtime.registry.snapshot = _snapshot(*runtime.new[:2], runtime.old[2])
    with pytest.raises(PluginRegistryVersionError, match="consumer-b"):
        await runtime.service.plan_registry_install("consumer-a", update=True)
    assert runtime.registry.downloaded == []
    assert_restored(runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["consumer", "source", "tamper"])
async def test_graph_or_identity_change_after_approval_cannot_publish(runtime, change):
    plan = await runtime.service.plan_registry_install("consumer-a", update=True)

    def alter(entry, path):
        if entry.plugin_id != "consumer-b":
            return
        if change == "consumer":
            runtime.config.plugins.packages["unseen-consumer"] = PluginSettings(
                dependency_package_sha256={LIBRARY_ID: runtime.old[0].package_sha256},
            )
        elif change == "source":
            record = runtime.config.plugins.packages["consumer-b"]
            if isinstance(record, dict):
                record["registry_source"] = "https://other.test/registry.json"
            else:
                record.registry_source = "https://other.test/registry.json"
        else:
            (runtime.root / LIBRARY_ID / "extra.py").write_text("tampered = True\n")

    runtime.registry.after_download = alter
    with pytest.raises(PluginDependencyConflictError):
        await runtime.service.update_from_registry(
            "consumer-a", expected_fingerprint=plan.fingerprint
        )
    assert runtime.events == []
    assert runtime.manager.get_package(LIBRARY_ID).manifest.version == "1.0.0"
    if change == "tamper":
        (runtime.root / LIBRARY_ID / "extra.py").unlink()
    elif change == "consumer":
        runtime.config.plugins.packages.pop("unseen-consumer")
    else:
        runtime.config.plugins.packages["consumer-b"] = PluginSettings.model_validate(
            runtime.before_config["consumer-b"]
        )
    assert_restored(runtime)


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["workers"], indirect=True)
async def test_real_workers_import_upgraded_library_and_old_processes_exit(runtime):
    from magi.plugins.process_runtime import ProcessPluginProxy

    workers = [
        runtime.manager.get_connection_plugin(item.connection_id) for item in runtime.connections
    ]
    assert all(isinstance(worker, ProcessPluginProxy) for worker in workers)
    before = [worker.read_settings_resource("login") for worker in workers]
    assert [item["version"] for item in before] == ["1.0.0", "1.0.0"]
    plan = await runtime.service.plan_registry_install("consumer-a", update=True)
    await runtime.service.update_from_registry("consumer-a", expected_fingerprint=plan.fingerprint)
    reloaded = [
        runtime.manager.get_connection_plugin(item.connection_id) for item in runtime.connections
    ]
    after = [worker.read_settings_resource("login") for worker in reloaded]
    assert [item["version"] for item in after] == ["2.0.0", "2.0.0"]
    assert {item["pid"] for item in before}.isdisjoint(item["pid"] for item in after)
    assert all(worker._process.poll() is not None for worker in workers)
    assert [
        item.model_dump(mode="json") for item in runtime.store.list()
    ] == runtime.before_connections


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_new_transitive_library_is_bound_and_removed_only_on_rollback(runtime, fail):
    leaf = _entry("new-leaf", kind="library", version="2.0.0")
    library = _entry(LIBRARY_ID, kind="library", version="2.0.0", depends_on=["new-leaf"])
    runtime.registry.snapshot = _snapshot(leaf, library, *runtime.new[1:])
    plan = await runtime.service.plan_registry_install("consumer-a", update=True)
    assert [item.entry.plugin_id for item in plan.changes] == [
        "new-leaf",
        LIBRARY_ID,
        "consumer-a",
        "consumer-b",
    ]
    assert plan.changes[0].action == "install"
    assert plan.changes[1].dependency_package_sha256 == {"new-leaf": leaf.package_sha256}
    if fail:
        runtime.failures.add(("consumer-b", "2.0.0"))
        with pytest.raises(RuntimeError, match="reload failure"):
            await runtime.service.update_from_registry(
                "consumer-a", expected_fingerprint=plan.fingerprint
            )
        assert not (runtime.root / "new-leaf").exists()
        assert_restored(runtime)
    else:
        await runtime.service.update_from_registry(
            "consumer-a", expected_fingerprint=plan.fingerprint
        )
        assert runtime.manager.get_package("new-leaf").manifest.version == "2.0.0"
        with pytest.raises(ValueError, match="still required"):
            runtime.manager.uninstall_plugin("new-leaf")


@pytest.mark.asyncio
async def test_new_target_can_coordinate_existing_consumers_without_deleting_them(runtime):
    third = _entry("consumer-c", version="2.0.0", depends_on=[LIBRARY_ID])
    runtime.registry.snapshot = _snapshot(*runtime.new, third)
    plan = await runtime.service.plan_registry_install("consumer-c")
    result = await runtime.service.install_from_registry(
        "consumer-c", expected_fingerprint=plan.fingerprint
    )
    assert result.target_state.manifest.version == "2.0.0"
    assert set(result.extra_installed) == {LIBRARY_ID, "consumer-a", "consumer-b"}
    assert set(runtime.config.plugins.packages) == {
        LIBRARY_ID,
        "consumer-a",
        "consumer-b",
        "consumer-c",
    }
    assert_connections_preserved(runtime)


@pytest.mark.asyncio
async def test_nested_reverse_consumers_also_need_new_releases(runtime):
    # Install a second shared library and a consumer above the first one.
    bridge = _entry("bridge", kind="library", depends_on=[LIBRARY_ID])
    third = _entry("consumer-c", depends_on=["bridge"])
    runtime.registry.snapshot = _snapshot(*runtime.old, bridge, third)
    await runtime.service.install_from_registry(
        "consumer-c", expected_fingerprint=runtime.service._build_registry_install_plan("consumer-c", snapshot=runtime.registry.snapshot, update=False).fingerprint
    )
    bridge_v2 = _entry("bridge", kind="library", version="2.0.0", depends_on=[LIBRARY_ID])
    third_v2 = _entry("consumer-c", version="2.0.0", depends_on=["bridge"])
    runtime.registry.snapshot = _snapshot(*runtime.new, bridge_v2, third_v2)
    plan = await runtime.service.plan_registry_install("consumer-a", update=True)
    assert {item.entry.plugin_id for item in plan.changes} == {
        LIBRARY_ID,
        "consumer-a",
        "consumer-b",
        "bridge",
        "consumer-c",
    }
    await runtime.service.update_from_registry("consumer-a", expected_fingerprint=plan.fingerprint)
    assert {state.manifest.version for state in runtime.manager.list_packages()} == {"2.0.0"}


@pytest.mark.asyncio
async def test_cancellation_after_partial_activation_waits_for_atomic_rollback(
    runtime, monkeypatch
):
    import threading

    reached = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = runtime.manager.load_plugin

    def hold_second(plugin_id):
        if (
            plugin_id == "consumer-b"
            and runtime.manager.get_package(plugin_id).manifest.version == "2.0.0"
        ):
            loop.call_soon_threadsafe(reached.set)
            assert release.wait(5)
        return original(plugin_id)

    monkeypatch.setattr(runtime.manager, "load_plugin", hold_second)
    plan = await runtime.service.plan_registry_install("consumer-a", update=True)
    task = asyncio.create_task(
        runtime.service.update_from_registry("consumer-a", expected_fingerprint=plan.fingerprint)
    )
    try:
        await asyncio.wait_for(reached.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert_restored(runtime)
    assert ("start", "consumer-a", "2.0.0") in runtime.events
    assert ("stop", "consumer-a", "2.0.0") in runtime.events


@pytest.mark.asyncio
async def test_concurrent_consumer_update_cannot_enter_reserved_plan(runtime, monkeypatch):
    import threading
    from magi.plugins.install_admission import PluginInstallConflictError

    reached = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = runtime.manager._install_staged_dependencies

    def hold_stage(directory, **kwargs):
        if "consumer-a" in directory.name:
            loop.call_soon_threadsafe(reached.set)
            assert release.wait(5)
        return original(directory, **kwargs)

    monkeypatch.setattr(runtime.manager, "_install_staged_dependencies", hold_stage)
    first_plan = await runtime.service.plan_registry_install("consumer-a", update=True)
    other_plan = await runtime.service.plan_registry_install("consumer-b", update=True)
    task = asyncio.create_task(
        runtime.service.update_from_registry(
            "consumer-a", expected_fingerprint=first_plan.fingerprint
        )
    )
    try:
        await asyncio.wait_for(reached.wait(), 5)
        with pytest.raises(PluginInstallConflictError):
            await runtime.service.update_from_registry(
                "consumer-b", expected_fingerprint=other_plan.fingerprint
            )
    finally:
        release.set()
    await asyncio.wait_for(task, 5)
    assert {state.manifest.version for state in runtime.manager.list_packages()} == {"2.0.0"}
    assert_connections_preserved(runtime)


@pytest.mark.asyncio
async def test_disabled_setup_connection_is_reloaded_without_enabling(runtime):
    old_setup = runtime.manager.setup_connection(runtime.disabled.connection_id)
    plan = await runtime.service.plan_registry_install("consumer-a", update=True)
    await runtime.service.update_from_registry("consumer-a", expected_fingerprint=plan.fingerprint)
    new_setup = runtime.manager._setup_instances[runtime.disabled.connection_id]
    assert new_setup is not old_setup
    assert new_setup.library_version == "2.0.0"
    assert not runtime.store.get(runtime.disabled.connection_id).enabled
    assert_connections_preserved(runtime)


@pytest.mark.asyncio
async def test_runtime_restart_during_failed_upgrade_is_drained_before_rollback(
    runtime, monkeypatch
):
    original = runtime.manager._drain_shutdowns_sync
    restarted = False
    connection = runtime.connections[0]

    def restart_after_drain(plugin_id):
        nonlocal restarted
        original(plugin_id)
        if (
            plugin_id == "consumer-a"
            and runtime.manager.get_package(plugin_id).manifest.version == "2.0.0"
            and not restarted
        ):
            restarted = True
            runtime.manager.load_connection(connection.connection_id)

    monkeypatch.setattr(runtime.manager, "_drain_shutdowns_sync", restart_after_drain)
    runtime.failures.add(("consumer-b", "2.0.0"))
    plan = await runtime.service.plan_registry_install("consumer-a", update=True)
    with pytest.raises(RuntimeError, match="reload failure"):
        await runtime.service.update_from_registry(
            "consumer-a", expected_fingerprint=plan.fingerprint
        )
    assert restarted
    assert runtime.events.count(("stop", "consumer-a", "2.0.0")) == 2
    assert_restored(runtime)


@pytest.mark.asyncio
async def test_consumer_with_forged_previous_dependency_hash_cannot_be_reapproved(runtime):
    record = PluginSettings.model_validate(runtime.config.plugins.packages["consumer-b"])
    record.dependency_package_sha256 = {LIBRARY_ID: "0" * 64}
    runtime.config.plugins.packages["consumer-b"] = record
    with pytest.raises(PluginDependencyConflictError, match="approved registry package"):
        await runtime.service.plan_registry_install("consumer-a", update=True)
    runtime.config.plugins.packages["consumer-b"] = PluginSettings.model_validate(
        runtime.before_config["consumer-b"]
    )
    assert_restored(runtime)


@pytest.mark.asyncio
async def test_late_cancellation_reports_completed_commit(runtime, monkeypatch):
    import threading

    reached = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = runtime.manager.install_coordinated_registry_plan

    def hold_committed(*args, **kwargs):
        result = original(*args, **kwargs)
        loop.call_soon_threadsafe(reached.set)
        assert release.wait(5)
        return result

    monkeypatch.setattr(runtime.manager, "install_coordinated_registry_plan", hold_committed)
    plan = await runtime.service.plan_registry_install("consumer-a", update=True)
    task = asyncio.create_task(
        runtime.service.update_from_registry("consumer-a", expected_fingerprint=plan.fingerprint)
    )
    try:
        await asyncio.wait_for(reached.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        release.set()
    assert (await task).manifest.version == "2.0.0"
    assert_connections_preserved(runtime)


@pytest.mark.asyncio
async def test_cancellation_does_not_hide_rollback_failure(runtime, monkeypatch):
    from magi.plugins.installation import PluginInstallRollbackError
    import threading

    reached = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def fail_recovery(*args, **kwargs):
        loop.call_soon_threadsafe(reached.set)
        assert release.wait(5)
        raise PluginInstallRollbackError("injected recovery failure")

    monkeypatch.setattr(runtime.manager, "install_coordinated_registry_plan", fail_recovery)
    plan = await runtime.service.plan_registry_install("consumer-a", update=True)
    task = asyncio.create_task(
        runtime.service.update_from_registry("consumer-a", expected_fingerprint=plan.fingerprint)
    )
    try:
        await asyncio.wait_for(reached.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        release.set()
    with pytest.raises(PluginInstallRollbackError):
        await task
    assert_restored(runtime)


@pytest.mark.asyncio
async def test_public_plan_route_reviews_and_executes_exact_closure(runtime, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from magi.api.routers import plugins_install_routes, plugins_registry_routes
    from magi.api.routers.plugins import plugins_router
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router

    for routes in (plugins_install_routes, plugins_registry_routes):
        monkeypatch.setattr(routes, "_plugin_install_service", lambda _: runtime.service)
        monkeypatch.setattr(routes, "_require_plugin_manager", lambda: runtime.manager)
    app = FastAPI()
    app.include_router(
        _build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"]),
        prefix="/api/plugins",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        review = await client.post(
            "/api/plugins/install/registry/plan",
            json={"plugin_id": "consumer-a", "update": True},
        )
        assert review.status_code == 200, review.text
        plan = review.json()
        assert {item["entry"]["plugin_id"] for item in plan["changes"]} == {
            "consumer-a", "consumer-b", LIBRARY_ID,
        }
        assert all(item["current_version"] == "1.0.0" for item in plan["changes"])
        assert all(item["entry"]["version"] == "2.0.0" for item in plan["changes"])
        assert runtime.manager.get_package(LIBRARY_ID).manifest.version == "1.0.0"
        rejected = await client.post(
            "/api/plugins/consumer-a/update",
            json={"plan_fingerprint": plan["registry_fingerprint"]},
        )
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["detail"]["error_code"] == "PLUGIN_INSTALL_PLAN_CHANGED"
        updated = await client.post(
            "/api/plugins/consumer-a/update",
            json={"plan_fingerprint": plan["fingerprint"]},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["manifest"]["version"] == "2.0.0"
        assert runtime.manager.get_package("consumer-b").manifest.version == "2.0.0"
