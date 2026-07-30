from __future__ import annotations

from pathlib import Path

import pytest

from magi.api.routers.plugins_common import _authoritative_official
from magi.config.plugin_models import PluginSettings
from magi.plugins.contracts import (
    PluginManifest,
    PluginPackageState,
    PluginRegistryEntry,
    PluginRegistryIndex,
)
from magi.plugins.install_service import PluginInstallService
from magi.plugins import package_files
from magi.plugins.registry_client import (
    DEFAULT_REGISTRY_URL,
    DEFAULT_REPO_URL,
    PluginRegistrySnapshot,
)
from magi.plugins.registry_provenance import (
    plugin_manifest_fingerprint,
    registry_install_fingerprint,
)


class _FakeManifest:
    def __init__(self, plugin_id: str, source: str, official: bool) -> None:
        self.plugin_id = plugin_id
        self.source = source
        self.official = official


def _cfg_with(
    plugin_id: str,
    official: bool,
    *,
    registry_url: str = DEFAULT_REGISTRY_URL,
    repo_url: str = DEFAULT_REPO_URL,
) -> dict[str, PluginSettings]:
    return {
        plugin_id: PluginSettings(
            official=official,
            install_origin="registry",
            registry_source=registry_url,
            registry_repo_url=repo_url,
        )
    }


def test_builtin_trusts_its_manifest_official() -> None:
    manifest = _FakeManifest("core-tools", "builtin", True)

    assert _authoritative_official(manifest, packages={}) is True


def test_canonical_registry_config_without_managed_identity_is_not_official() -> None:
    manifest = _FakeManifest("calendar", "external", False)

    assert (
        _authoritative_official(
            manifest,
            packages=_cfg_with("calendar", True),
        )
        is False
    )


def test_canonical_managed_registry_package_can_be_official(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: tmp_path)
    plugin_dir = tmp_path / "calendar"
    plugin_dir.mkdir()
    manifest_path = plugin_dir / "plugin.toml"
    manifest_path.write_text("[plugin]\n", encoding="utf-8")
    manifest = PluginManifest(
        id="calendar",
        name="Calendar",
        version="1.0.0",
        source="external",
        plugin_dir=str(plugin_dir),
        manifest_path=str(manifest_path),
    )
    configured = PluginSettings(
        enabled=True,
        trusted=True,
        source="external",
        manifest_path=str(manifest_path),
        official=True,
        install_origin="registry",
        registry_source=DEFAULT_REGISTRY_URL,
        registry_repo_url=DEFAULT_REPO_URL,
        registry_entry_fingerprint="entry-calendar",
        registry_manifest_fingerprint=plugin_manifest_fingerprint(manifest),
    )

    assert _authoritative_official(manifest, packages={"calendar": configured}) is True


@pytest.mark.parametrize(
    ("registry_url", "repo_url"),
    [
        ("https://mirror.example/registry.json", DEFAULT_REPO_URL),
        (DEFAULT_REGISTRY_URL, "https://github.com/example/mirror.git"),
    ],
)
def test_custom_registry_or_repository_cannot_claim_official_status(
    registry_url: str,
    repo_url: str,
) -> None:
    manifest = _FakeManifest("calendar", "external", False)

    assert (
        _authoritative_official(
            manifest,
            packages=_cfg_with(
                "calendar",
                True,
                registry_url=registry_url,
                repo_url=repo_url,
            ),
        )
        is False
    )


def test_non_builtin_ignores_forged_manifest_official() -> None:
    manifest = _FakeManifest("evil", "external", True)

    assert (
        _authoritative_official(
            manifest,
            packages=_cfg_with("evil", False),
        )
        is False
    )


def test_legacy_official_config_without_registry_provenance_is_not_authoritative() -> None:
    manifest = _FakeManifest("legacy", "external", False)

    assert (
        _authoritative_official(
            manifest,
            packages={"legacy": PluginSettings(official=True)},
        )
        is False
    )


class _FakeManager:
    def __init__(self) -> None:
        self.install_kwargs: dict | None = None

    def installed_plugin_ids(self) -> set[str]:
        return set()

    def install_plugin_from_directory(self, plugin_dir: Path, **kwargs):
        self.install_kwargs = {"plugin_dir": plugin_dir, **kwargs}
        return PluginPackageState(
            manifest=PluginManifest(
                id="calendar",
                name="Calendar",
                version="1.0.0",
                source="external",
            ),
            enabled=True,
        )


class _FakeRegistry:
    def __init__(self, snapshot: PluginRegistrySnapshot) -> None:
        self.snapshot = snapshot

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
        assert deadline_monotonic is not None
        assert snapshot is self.snapshot
        assert dest_dir is not None
        plugin_dir = dest_dir / entry.plugin_id
        plugin_dir.mkdir()
        return plugin_dir


def _snapshot(*, official_source: bool) -> PluginRegistrySnapshot:
    entry = PluginRegistryEntry(
        plugin_id="calendar",
        name="Calendar",
        version="1.0.0",
        path="plugins/calendar",
        official=True,
    )
    registry_url = DEFAULT_REGISTRY_URL if official_source else "https://mirror.example/index.json"
    index = PluginRegistryIndex(plugins=[entry], repo_url=DEFAULT_REPO_URL)
    return PluginRegistrySnapshot(
        index=index,
        registry_url=registry_url,
        repo_url=DEFAULT_REPO_URL,
        install_fingerprint=registry_install_fingerprint(
            index,
            registry_url=registry_url,
            repo_url=DEFAULT_REPO_URL,
        ),
        official_source=official_source,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("official_source", [True, False])
async def test_install_passes_only_effective_official_value_to_manager(
    monkeypatch: pytest.MonkeyPatch,
    official_source: bool,
) -> None:
    snapshot = _snapshot(official_source=official_source)
    manager = _FakeManager()
    service = PluginInstallService(
        registry_client=_FakeRegistry(snapshot),
        plugin_manager=manager,
    )
    manifest = PluginManifest(
        id="calendar",
        name="Calendar",
        version="1.0.0",
    )
    monkeypatch.setattr(
        "magi.plugins.install_service._validate_registry_package_directory",
        lambda _plugin_dir, _entry: manifest,
    )

    await service.install_from_registry(
        "calendar",
        expected_fingerprint=snapshot.install_fingerprint,
    )

    assert manager.install_kwargs is not None
    assert manager.install_kwargs["official"] is official_source
    assert manager.install_kwargs["install_origin"] == "registry"
    assert manager.install_kwargs["registry_source"] == snapshot.registry_url
    assert manager.install_kwargs["registry_repo_url"] == snapshot.repo_url
