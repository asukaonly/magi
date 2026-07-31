from __future__ import annotations

from pathlib import Path

import pytest

from magi.plugins.contracts import (
    PluginCapability,
    PluginManifest,
    PluginPackageState,
    PluginRegistryEntry,
    PluginRegistryIndex,
)
from magi.plugins.install_service import (
    PluginInstallService,
    PluginRegistrySnapshotMismatchError,
    PluginRegistryVersionError,
)
from magi.plugins.registry_client import PluginRegistrySnapshot
from magi.plugins.registry_provenance import registry_install_fingerprint


def _entry(**updates) -> PluginRegistryEntry:
    payload = {
        "plugin_id": "demo-plugin",
        "name": "Demo Plugin",
        "version": "1.0.0",
        "package_sha256": "a" * 64,
        "path": "plugins/demo-plugin",
    }
    payload.update(updates)
    return PluginRegistryEntry.model_validate(payload)


def _snapshot(
    *entries: PluginRegistryEntry,
    registry_url: str = "https://example.test/registry.json",
    repo_url: str = "https://github.com/example/plugins.git",
    official_source: bool = False,
) -> PluginRegistrySnapshot:
    index = PluginRegistryIndex(
        plugins=list(entries),
        registry_version="4",
        repo_url=repo_url,
    )
    return PluginRegistrySnapshot(
        index=index,
        registry_url=registry_url,
        repo_url=repo_url,
        install_fingerprint=registry_install_fingerprint(
            index,
            registry_url=registry_url,
            repo_url=repo_url,
        ),
        official_source=official_source,
    )


class _Registry:
    def __init__(self, *snapshots: PluginRegistrySnapshot) -> None:
        self.snapshots = list(snapshots)
        self.last_snapshot = snapshots[-1]
        self.clone_calls: list[PluginRegistrySnapshot] = []
        self.snapshot_deadlines: list[float | None] = []

    async def fetch_snapshot(
        self,
        *,
        force: bool = False,
        deadline_monotonic: float | None = None,
    ) -> PluginRegistrySnapshot:
        self.snapshot_deadlines.append(deadline_monotonic)
        if self.snapshots:
            self.last_snapshot = self.snapshots.pop(0)
        return self.last_snapshot

    async def clone_plugin(
        self,
        entry: PluginRegistryEntry,
        *,
        snapshot: PluginRegistrySnapshot,
        dest_dir: Path | None = None,
        deadline_monotonic: float | None = None,
    ) -> Path:
        assert deadline_monotonic is not None
        self.clone_calls.append(snapshot)
        assert dest_dir is not None
        plugin_dir = dest_dir / entry.plugin_id
        plugin_dir.mkdir()
        return plugin_dir


class _Manager:
    def __init__(self, installed: PluginPackageState | None = None) -> None:
        self.install_calls: list[dict] = []
        self.installed = installed

    def installed_plugin_ids(self) -> set[str]:
        if self.installed is None:
            return set()
        return {self.installed.manifest.plugin_id}

    def get_package(self, plugin_id: str):
        if self.installed is not None and self.installed.manifest.plugin_id == plugin_id:
            return self.installed
        return None

    def install_plugin_from_directory(self, plugin_dir: Path, **kwargs):
        self.install_calls.append({"plugin_dir": plugin_dir, **kwargs})
        return PluginPackageState(
            manifest=PluginManifest(
                id="demo-plugin",
                name="Demo Plugin",
                version="1.0.0",
            ),
            enabled=True,
            trusted=True,
        )


@pytest.mark.asyncio
async def test_registry_install_rejects_stale_consent_before_download() -> None:
    approved = _snapshot(_entry())
    changed = _snapshot(_entry(version="2.0.0"))
    registry = _Registry(changed)
    service = PluginInstallService(registry_client=registry, plugin_manager=_Manager())

    with pytest.raises(PluginRegistrySnapshotMismatchError):
        await service.install_from_registry(
            "demo-plugin",
            expected_fingerprint=approved.install_fingerprint,
        )

    assert registry.clone_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [
        _snapshot(_entry(version="2.0.0")),
        _snapshot(
            _entry(
                capabilities=[
                    PluginCapability(
                        capability="network",
                        scope=["example.com"],
                    )
                ]
            )
        ),
        _snapshot(
            _entry(depends_on=["shared-library"]),
            _entry(plugin_id="shared-library", kind="library"),
        ),
        _snapshot(
            _entry(),
            repo_url="https://github.com/example/other-plugins.git",
        ),
    ],
)
async def test_registry_install_rechecks_consent_after_manifest_validation(
    changed: PluginRegistrySnapshot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = _snapshot(_entry())
    registry = _Registry(approved, changed)
    manager = _Manager()
    service = PluginInstallService(registry_client=registry, plugin_manager=manager)
    manifest = PluginManifest(
        id="demo-plugin",
        name="Demo Plugin",
        version="1.0.0",
    )
    monkeypatch.setattr(
        "magi.plugins.install_service._validate_registry_package_directory",
        lambda _plugin_dir, _entry: manifest,
    )

    with pytest.raises(PluginRegistrySnapshotMismatchError):
        await service.install_from_registry(
            "demo-plugin",
            expected_fingerprint=approved.install_fingerprint,
        )

    assert len(registry.clone_calls) == 1
    assert manager.install_calls == []


@pytest.mark.asyncio
async def test_registry_install_uses_one_snapshot_and_effective_official_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = _snapshot(_entry(official=True), official_source=False)
    registry = _Registry(approved, approved)
    manager = _Manager()
    service = PluginInstallService(registry_client=registry, plugin_manager=manager)
    manifest = PluginManifest(
        id="demo-plugin",
        name="Demo Plugin",
        version="1.0.0",
        official=True,
    )
    monkeypatch.setattr(
        "magi.plugins.install_service._validate_registry_package_directory",
        lambda _plugin_dir, _entry: manifest,
    )

    result = await service.install_from_registry(
        "demo-plugin",
        expected_fingerprint=approved.install_fingerprint,
    )

    assert result.target_state.manifest.plugin_id == "demo-plugin"
    assert registry.clone_calls == [approved]
    assert registry.snapshot_deadlines
    assert all(deadline is not None for deadline in registry.snapshot_deadlines)
    assert manager.install_calls[0]["official"] is False
    assert manager.install_calls[0]["registry_source"] == approved.registry_url
    assert manager.install_calls[0]["registry_repo_url"] == approved.repo_url


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_version", ["2.0.0", "1.9.9"])
async def test_registry_update_rejects_same_or_older_version_before_download(
    remote_version: str,
) -> None:
    snapshot = _snapshot(_entry(version=remote_version))
    registry = _Registry(snapshot)
    manager = _Manager(
        PluginPackageState(
            manifest=PluginManifest(
                id="demo-plugin",
                name="Demo Plugin",
                version="2.0.0",
                source="external",
            ),
            enabled=True,
            trusted=True,
        )
    )
    service = PluginInstallService(registry_client=registry, plugin_manager=manager)

    with pytest.raises(PluginRegistryVersionError, match="newer"):
        await service._install_from_registry_admitted(
            "demo-plugin",
            expected_fingerprint=snapshot.install_fingerprint,
            expected_registry_update_source=(
                snapshot.registry_url,
                snapshot.repo_url,
            ),
        )

    assert registry.clone_calls == []
