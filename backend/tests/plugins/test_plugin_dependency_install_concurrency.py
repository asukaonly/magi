from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import threading

import pytest

from magi.config.models import AppConfig
from magi.plugins import package_files
from magi.plugins.contracts import PluginRegistryEntry, PluginRegistryIndex
from magi.plugins.install_service import (
    PluginDependencyConflictError,
    PluginInstallService,
)
from magi.plugins.manager import PluginManager
from magi.plugins.package_identity import compute_package_sha256
from magi.plugins.registry_client import PluginRegistrySnapshot
from magi.plugins.registry_provenance import registry_install_fingerprint
from magi.plugins.sources import SourceRegistry
from magi.tools.registry import ToolRegistry

REGISTRY_URL = "https://example.test/registry.json"
REPO_URL = "https://github.com/example/plugins.git"
LIBRARY_ID = "shared-library"


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
    def save(updates: dict[str, object]) -> bool:
        _apply_updates(config, updates)
        return True

    def delete(plugin_id: str) -> bool:
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
    kind: str = "plugin",
    version: str = "1.0.0",
    depends_on: list[str] | None = None,
) -> PluginRegistryEntry:
    entry = PluginRegistryEntry(
        plugin_id=plugin_id,
        name=plugin_id,
        version=version,
        package_sha256="0" * 64,
        description="Concurrent dependency test package",
        author="Test",
        path=plugin_id,
        kind=kind,
        depends_on=depends_on or [],
    )
    with tempfile.TemporaryDirectory() as temporary_root:
        plugin_dir = _write_package(Path(temporary_root), entry)
        return entry.model_copy(update={"package_sha256": compute_package_sha256(plugin_dir)})


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


def _write_package(dest_root: Path, entry: PluginRegistryEntry) -> Path:
    plugin_dir = dest_root / entry.plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    dependencies = ", ".join(f'"{item}"' for item in entry.depends_on)
    entrypoint = (
        ""
        if entry.kind == "library"
        else '\nentry_module = "plugin"\nentry_class = "ConcurrentPlugin"'
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
        (plugin_dir / "__init__.py").write_text(
            f'VERSION = "{entry.version}"\n',
            encoding="utf-8",
        )
    else:
        (plugin_dir / "plugin.py").write_text(
            """from magi_plugin_sdk import Plugin


class ConcurrentPlugin(Plugin):
    pass
""".strip(),
            encoding="utf-8",
        )
    return plugin_dir


class _InstallInterleaving:
    def __init__(
        self,
        *,
        target_goal: int = 2,
        hold_first_target: bool = False,
    ) -> None:
        self.targets_ready = asyncio.Event()
        self.first_library_installed = asyncio.Event()
        self.first_target_waiting = asyncio.Event()
        self.allow_first_target = asyncio.Event()
        self.target_count = 0
        self.target_goal = target_goal
        self.hold_first_target = hold_first_target
        self.root_labels: dict[Path, str] = {}

    async def wait_before_returning_target(self, label: str) -> None:
        self.target_count += 1
        if self.target_count == self.target_goal:
            self.targets_ready.set()
        await self.targets_ready.wait()
        if label == "first" and self.hold_first_target:
            self.first_target_waiting.set()
            await self.allow_first_target.wait()
        if label == "second":
            await self.first_library_installed.wait()


class _Registry:
    def __init__(
        self,
        snapshot: PluginRegistrySnapshot,
        interleaving: _InstallInterleaving,
    ) -> None:
        self.snapshot = snapshot
        self.interleaving = interleaving

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
        assert deadline_monotonic is not None
        task = asyncio.current_task()
        assert task is not None
        label = task.get_name()
        self.interleaving.root_labels[dest_dir] = label
        plugin_dir = _write_package(dest_dir, entry)
        if entry.kind == "plugin":
            await self.interleaving.wait_before_returning_target(label)
        return plugin_dir


def _manager(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    interleaving: _InstallInterleaving,
) -> tuple[PluginManager, list[str]]:
    user_root = tmp_path / "user-plugins"
    config = AppConfig()
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: user_root)
    manager = PluginManager(
        tool_registry=ToolRegistry(),
        source_registry=SourceRegistry(),
        request_source_schedule_refresh=lambda: None,
        search_paths=[user_root],
    )
    original_install = manager.install_plugin_from_directory
    library_installs: list[str] = []
    install_lock = threading.Lock()
    loop = asyncio.get_running_loop()

    def track_install(plugin_dir: Path, **kwargs):
        result = original_install(plugin_dir, **kwargs)
        if plugin_dir.name == LIBRARY_ID:
            label = interleaving.root_labels[plugin_dir.parent]
            with install_lock:
                library_installs.append(label)
            if label == "first":
                loop.call_soon_threadsafe(interleaving.first_library_installed.set)
        return result

    monkeypatch.setattr(manager, "install_plugin_from_directory", track_install)
    return manager, library_installs


@pytest.mark.asyncio
async def test_concurrent_targets_reuse_identical_shared_library(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry(LIBRARY_ID, kind="library")
    first_target = _entry("first-target", depends_on=[LIBRARY_ID])
    second_target = _entry("second-target", depends_on=[LIBRARY_ID])
    snapshot = _snapshot(library, first_target, second_target)
    interleaving = _InstallInterleaving()
    manager, library_installs = _manager(monkeypatch, tmp_path, interleaving)
    registry = _Registry(snapshot, interleaving)
    service = PluginInstallService(registry_client=registry, plugin_manager=manager)
    event_loop_thread = threading.get_ident()
    validation_threads: list[int] = []
    original_validation = service._assert_installed_library_reusable

    def track_validation(*args, **kwargs) -> None:
        validation_threads.append(threading.get_ident())
        original_validation(*args, **kwargs)

    monkeypatch.setattr(
        service,
        "_assert_installed_library_reusable",
        track_validation,
    )

    first = asyncio.create_task(
        service.install_from_registry(
            "first-target",
            expected_fingerprint=snapshot.install_fingerprint,
        ),
        name="first",
    )
    second = asyncio.create_task(
        service.install_from_registry(
            "second-target",
            expected_fingerprint=snapshot.install_fingerprint,
        ),
        name="second",
    )
    results = await asyncio.gather(first, second)

    assert [result.target_state.manifest.plugin_id for result in results] == [
        "first-target",
        "second-target",
    ]
    assert library_installs == ["first"]
    assert manager.get_package(LIBRARY_ID) is not None
    assert manager.get_package("first-target") is not None
    assert manager.get_package("second-target") is not None
    assert validation_threads
    assert event_loop_thread not in validation_threads


@pytest.mark.asyncio
async def test_preinstalled_library_validation_runs_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    library = _entry(LIBRARY_ID, kind="library")
    first_target = _entry("first-target", depends_on=[LIBRARY_ID])
    second_target = _entry("second-target", depends_on=[LIBRARY_ID])
    snapshot = _snapshot(library, first_target, second_target)
    interleaving = _InstallInterleaving(target_goal=1)
    manager, _ = _manager(monkeypatch, tmp_path, interleaving)
    service = PluginInstallService(
        registry_client=_Registry(snapshot, interleaving),
        plugin_manager=manager,
    )

    await service.install_from_registry(
        "first-target",
        expected_fingerprint=snapshot.install_fingerprint,
    )

    event_loop_thread = threading.get_ident()
    validation_threads: list[int] = []
    original_validation = service._assert_installed_library_reusable

    def track_validation(*args, **kwargs) -> None:
        validation_threads.append(threading.get_ident())
        original_validation(*args, **kwargs)

    monkeypatch.setattr(
        service,
        "_assert_installed_library_reusable",
        track_validation,
    )

    await service.install_from_registry(
        "second-target",
        expected_fingerprint=snapshot.install_fingerprint,
    )

    assert validation_threads
    assert event_loop_thread not in validation_threads


@pytest.mark.asyncio
async def test_concurrent_target_cannot_replace_incompatible_shared_library(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_library = _entry(LIBRARY_ID, kind="library", version="1.0.0")
    second_library = _entry(LIBRARY_ID, kind="library", version="2.0.0")
    first_target = _entry("first-target", depends_on=[LIBRARY_ID])
    second_target = _entry("second-target", depends_on=[LIBRARY_ID])
    first_snapshot = _snapshot(first_library, first_target)
    second_snapshot = _snapshot(second_library, second_target)
    interleaving = _InstallInterleaving(
        target_goal=1,
        hold_first_target=True,
    )
    manager, library_installs = _manager(monkeypatch, tmp_path, interleaving)
    first_service = PluginInstallService(
        registry_client=_Registry(first_snapshot, interleaving),
        plugin_manager=manager,
    )
    second_service = PluginInstallService(
        registry_client=_Registry(second_snapshot, interleaving),
        plugin_manager=manager,
    )

    first = asyncio.create_task(
        first_service.install_from_registry(
            "first-target",
            expected_fingerprint=first_snapshot.install_fingerprint,
        ),
        name="first",
    )
    await asyncio.wait_for(interleaving.first_target_waiting.wait(), timeout=5)
    second = asyncio.create_task(
        second_service.install_from_registry(
            "second-target",
            expected_fingerprint=second_snapshot.install_fingerprint,
        ),
        name="second",
    )
    try:
        second_result = await asyncio.wait_for(second, timeout=5)
    except BaseException as exc:
        second_result = exc
    finally:
        interleaving.allow_first_target.set()
    first_result = await asyncio.wait_for(first, timeout=5)

    assert not isinstance(first_result, BaseException)
    assert isinstance(second_result, PluginDependencyConflictError)
    assert library_installs == ["first"]
    library_state = manager.get_package(LIBRARY_ID)
    assert library_state is not None
    assert library_state.manifest.version == "1.0.0"
    assert manager.get_package("first-target") is not None
    assert manager.get_package("second-target") is None
