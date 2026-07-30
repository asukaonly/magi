from __future__ import annotations

from pathlib import Path

import pytest

from magi.config.models import AppConfig, PluginSettings
from magi.plugins.contracts import (
    PluginManifest,
    PluginPackageState,
    PluginRegistryEntry,
    PluginRegistryIndex,
)
from magi.plugins.install_service import (
    PluginDependencyConflictError,
    PluginInstallService,
)
from magi.plugins.registry_client import PluginRegistrySnapshot
from magi.plugins.registry_provenance import (
    plugin_manifest_fingerprint,
    registry_entry_fingerprint,
    registry_install_fingerprint,
)

REGISTRY_URL = "https://example.test/registry.json"
REPO_URL = "https://github.com/example/plugins.git"


def _library_entry() -> PluginRegistryEntry:
    return PluginRegistryEntry(
        plugin_id="shared-library",
        name="Shared Library",
        version="1.0.0",
        path="plugins/shared-library",
        author="Example",
        kind="library",
    )


def _target_entry() -> PluginRegistryEntry:
    return PluginRegistryEntry(
        plugin_id="requested-plugin",
        name="Requested Plugin",
        version="1.0.0",
        path="plugins/requested-plugin",
        author="Example",
        depends_on=["shared-library"],
    )


def _snapshot() -> PluginRegistrySnapshot:
    index = PluginRegistryIndex(
        plugins=[_target_entry(), _library_entry()],
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


def _library_manifest(
    tmp_path: Path,
    *,
    kind: str = "library",
    version: str = "1.0.0",
) -> PluginManifest:
    plugin_dir = tmp_path / "shared-library"
    plugin_dir.mkdir(exist_ok=True)
    manifest_path = plugin_dir / "plugin.toml"
    manifest_path.write_text("[plugin]\n", encoding="utf-8")
    return PluginManifest(
        id="shared-library",
        name="Shared Library",
        version=version,
        author="Example",
        kind=kind,
        source="external",
        plugin_dir=str(plugin_dir),
        manifest_path=str(manifest_path),
    )


class _Manager:
    def __init__(self, state: PluginPackageState) -> None:
        self.state = state

    def get_package(self, plugin_id: str) -> PluginPackageState | None:
        return self.state if plugin_id == "shared-library" else None


def _valid_config(
    manifest: PluginManifest,
    snapshot: PluginRegistrySnapshot,
) -> PluginSettings:
    return PluginSettings(
        enabled=True,
        trusted=True,
        source="external",
        manifest_path=manifest.manifest_path,
        install_origin="registry",
        registry_source=snapshot.registry_url,
        registry_repo_url=snapshot.repo_url,
        registry_entry_fingerprint=registry_entry_fingerprint(
            _library_entry(),
            registry_url=snapshot.registry_url,
            repo_url=snapshot.repo_url,
        ),
        registry_manifest_fingerprint=plugin_manifest_fingerprint(manifest),
    )


def _resolve_with_installed_library(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    kind: str = "library",
    version: str = "1.0.0",
    configure=None,
) -> list[PluginRegistryEntry]:
    snapshot = _snapshot()
    manifest = _library_manifest(tmp_path, kind=kind, version=version)
    state = PluginPackageState(
        manifest=manifest,
        enabled=True,
        trusted=True,
    )
    config = AppConfig()
    package_config = _valid_config(manifest, snapshot)
    if configure is not None:
        package_config = configure(package_config)
    config.plugins.packages["shared-library"] = package_config
    monkeypatch.setattr("magi.plugins.install_service.get_config", lambda: config)
    service = PluginInstallService(
        registry_client=object(),
        plugin_manager=_Manager(state),
    )
    entries = {entry.plugin_id: entry for entry in snapshot.index.plugins}
    return service._resolve_install_closure(
        "requested-plugin",
        snapshot=snapshot,
        entries_by_id=entries,
        already_installed={"shared-library"},
    )


def test_matching_registry_library_is_reused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    order = _resolve_with_installed_library(monkeypatch, tmp_path)

    assert [entry.plugin_id for entry in order] == ["requested-plugin"]


@pytest.mark.parametrize(
    ("kind", "version", "configure"),
    [
        ("plugin", "1.0.0", None),
        (
            "library",
            "1.0.0",
            lambda config: config.model_copy(update={"install_origin": "upload"}),
        ),
        ("library", "0.9.0", None),
        (
            "library",
            "1.0.0",
            lambda config: config.model_copy(
                update={"registry_source": "https://other.example/registry.json"}
            ),
        ),
        (
            "library",
            "1.0.0",
            lambda config: config.model_copy(update={"registry_entry_fingerprint": None}),
        ),
    ],
)
def test_untrusted_or_stale_installed_package_cannot_satisfy_dependency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kind: str,
    version: str,
    configure,
) -> None:
    with pytest.raises(PluginDependencyConflictError):
        _resolve_with_installed_library(
            monkeypatch,
            tmp_path,
            kind=kind,
            version=version,
            configure=configure,
        )
