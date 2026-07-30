from __future__ import annotations

from pathlib import Path

import pytest

from magi.config.models import AppConfig
from magi.plugins import package_files
from magi.plugins.contracts import PluginRegistryEntry, PluginRegistryIndex
from magi.plugins.install_service import (
    DirectLibraryInstallError,
    MAX_PLUGIN_DEPENDENCY_CLOSURE,
    PluginInstallService,
)
from magi.plugins.registry_client import PluginRegistrySnapshot
from magi.plugins.registry_provenance import registry_install_fingerprint


def _entry(
    plugin_id: str,
    *,
    kind: str = "plugin",
    depends_on: list[str] | None = None,
) -> PluginRegistryEntry:
    return PluginRegistryEntry(
        plugin_id=plugin_id,
        name=plugin_id,
        version="1.0.0",
        kind=kind,
        depends_on=depends_on or [],
    )


class _Registry:
    def __init__(self, *entries: PluginRegistryEntry) -> None:
        self.entries = {entry.plugin_id: entry for entry in entries}
        self.clone_calls: list[str] = []
        index = PluginRegistryIndex(
            plugins=list(entries),
            repo_url="https://github.com/example/plugins.git",
        )
        self.snapshot = PluginRegistrySnapshot(
            index=index,
            registry_url="https://example.test/registry.json",
            repo_url=index.repo_url,
            install_fingerprint=registry_install_fingerprint(
                index,
                registry_url="https://example.test/registry.json",
                repo_url=index.repo_url,
            ),
            official_source=False,
        )

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
        dest_dir=None,
        deadline_monotonic: float | None = None,
    ):
        self.clone_calls.append(entry.plugin_id)
        raise AssertionError("unsafe dependency closure reached package download")


class _NoPackagesManager:
    def installed_plugin_ids(self) -> set[str]:
        return set()

    def get_package(self, _plugin_id: str):
        return None


@pytest.mark.asyncio
async def test_direct_library_install_is_rejected_before_download() -> None:
    registry = _Registry(_entry("shared-library", kind="library"))
    service = PluginInstallService(
        registry_client=registry,
        plugin_manager=_NoPackagesManager(),
    )

    with pytest.raises(DirectLibraryInstallError, match="cannot be installed directly"):
        await service.install_from_registry(
            "shared-library",
            expected_fingerprint=registry.snapshot.install_fingerprint,
        )

    assert registry.clone_calls == []


@pytest.mark.asyncio
async def test_plugin_dependency_cannot_be_another_runnable_plugin() -> None:
    registry = _Registry(
        _entry("requested-plugin", depends_on=["hidden-plugin"]),
        _entry("hidden-plugin"),
    )
    service = PluginInstallService(
        registry_client=registry,
        plugin_manager=_NoPackagesManager(),
    )

    with pytest.raises(DirectLibraryInstallError, match="must be library packages"):
        await service.install_from_registry(
            "requested-plugin",
            expected_fingerprint=registry.snapshot.install_fingerprint,
        )

    assert registry.clone_calls == []


@pytest.mark.asyncio
async def test_installed_runnable_plugin_cannot_bypass_dependency_validation() -> None:
    registry = _Registry(
        _entry("requested-plugin", depends_on=["already-installed-plugin"]),
        _entry("already-installed-plugin"),
    )
    service = PluginInstallService(
        registry_client=registry,
        plugin_manager=_NoPackagesManager(),
    )

    with pytest.raises(DirectLibraryInstallError, match="runnable plugin"):
        service._resolve_install_closure(
            "requested-plugin",
            snapshot=registry.snapshot,
            entries_by_id=registry.entries,
            already_installed={"already-installed-plugin"},
        )

    assert registry.clone_calls == []


@pytest.mark.asyncio
async def test_library_cannot_pull_in_a_runnable_plugin() -> None:
    registry = _Registry(
        _entry("requested-plugin", depends_on=["shared-library"]),
        _entry(
            "shared-library",
            kind="library",
            depends_on=["hidden-plugin"],
        ),
        _entry("hidden-plugin"),
    )
    service = PluginInstallService(
        registry_client=registry,
        plugin_manager=_NoPackagesManager(),
    )

    with pytest.raises(DirectLibraryInstallError, match="hidden-plugin"):
        await service.install_from_registry(
            "requested-plugin",
            expected_fingerprint=registry.snapshot.install_fingerprint,
        )

    assert registry.clone_calls == []


@pytest.mark.asyncio
async def test_library_dependency_cycles_are_rejected_before_download() -> None:
    registry = _Registry(
        _entry("requested-plugin", depends_on=["library-a"]),
        _entry("library-a", kind="library", depends_on=["library-b"]),
        _entry("library-b", kind="library", depends_on=["library-a"]),
    )
    service = PluginInstallService(
        registry_client=registry,
        plugin_manager=_NoPackagesManager(),
    )

    with pytest.raises(ValueError, match="Cyclic plugin dependency"):
        await service.install_from_registry(
            "requested-plugin",
            expected_fingerprint=registry.snapshot.install_fingerprint,
        )

    assert registry.clone_calls == []


@pytest.mark.asyncio
async def test_library_dependency_chain_is_resolved_before_target() -> None:
    registry = _Registry(
        _entry("requested-plugin", depends_on=["library-a"]),
        _entry("library-a", kind="library", depends_on=["library-b"]),
        _entry("library-b", kind="library"),
    )
    service = PluginInstallService(
        registry_client=registry,
        plugin_manager=_NoPackagesManager(),
    )

    order = service._resolve_install_closure(
        "requested-plugin",
        snapshot=registry.snapshot,
        entries_by_id=registry.entries,
        already_installed=set(),
    )

    assert [entry.plugin_id for entry in order] == [
        "library-b",
        "library-a",
        "requested-plugin",
    ]


@pytest.mark.asyncio
async def test_oversized_dependency_closure_is_rejected_before_download() -> None:
    libraries = [
        _entry(
            f"library-{index}",
            kind="library",
            depends_on=([f"library-{index + 1}"] if index < MAX_PLUGIN_DEPENDENCY_CLOSURE else []),
        )
        for index in range(MAX_PLUGIN_DEPENDENCY_CLOSURE + 1)
    ]
    registry = _Registry(
        _entry("requested-plugin", depends_on=["library-0"]),
        *libraries,
    )
    service = PluginInstallService(
        registry_client=registry,
        plugin_manager=_NoPackagesManager(),
    )

    with pytest.raises(ValueError, match="closure exceeds"):
        await service.install_from_registry(
            "requested-plugin",
            expected_fingerprint=registry.snapshot.install_fingerprint,
        )

    assert registry.clone_calls == []


@pytest.mark.asyncio
async def test_registry_install_without_runtime_manager_never_publishes_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entry = _entry("requested-plugin")
    registry = _Registry(entry)
    user_root = tmp_path / "managed-plugins"
    config = AppConfig()

    async def clone_plugin(
        requested: PluginRegistryEntry,
        *,
        snapshot: PluginRegistrySnapshot,
        dest_dir: Path | None = None,
        deadline_monotonic: float | None = None,
    ) -> Path:
        registry.clone_calls.append(requested.plugin_id)
        assert requested is entry
        assert snapshot is registry.snapshot
        assert dest_dir is not None
        assert deadline_monotonic is not None
        plugin_dir = dest_dir / entry.plugin_id
        plugin_dir.mkdir()
        (plugin_dir / "plugin.toml").write_text(
            f"""
[plugin]
id = "requested-plugin"
name = "requested-plugin"
version = "1.0.0"
author = "{entry.author}"
""".strip(),
            encoding="utf-8",
        )
        return plugin_dir

    monkeypatch.setattr(registry, "clone_plugin", clone_plugin)
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: user_root)
    monkeypatch.setattr("magi.plugins.install_service.get_config", lambda: config)
    service = PluginInstallService(registry_client=registry, plugin_manager=None)

    with pytest.raises(RuntimeError, match="Plugin manager is not initialized"):
        await service.install_from_registry(
            entry.plugin_id,
            expected_fingerprint=registry.snapshot.install_fingerprint,
        )

    assert not user_root.exists()
    assert entry.plugin_id not in config.plugins.packages
    assert registry.clone_calls == []
