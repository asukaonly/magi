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
from magi.plugins import package_files
from magi.plugins.package_identity import (
    compute_installed_package_sha256,
    compute_installed_source_sha256,
)
from magi.plugins.registry_client import PluginRegistrySnapshot
from magi.plugins.registry_provenance import registry_install_fingerprint

REGISTRY_URL = "https://example.test/registry.json"
REPO_URL = "https://github.com/example/plugins.git"
TARGET_PACKAGE_SHA256 = "1" * 64


def _library_entry(package_sha256: str) -> PluginRegistryEntry:
    return PluginRegistryEntry(
        plugin_id="shared-library",
        name="Shared Library",
        version="1.0.0",
        package_sha256=package_sha256,
        path="plugins/shared-library",
        author="Example",
        kind="library",
    )


def _target_entry() -> PluginRegistryEntry:
    return PluginRegistryEntry(
        plugin_id="requested-plugin",
        name="Requested Plugin",
        version="1.0.0",
        package_sha256=TARGET_PACKAGE_SHA256,
        path="plugins/requested-plugin",
        author="Example",
        depends_on=["shared-library"],
    )


def _snapshot(*, library_package_sha256: str) -> PluginRegistrySnapshot:
    index = PluginRegistryIndex(
        plugins=[_target_entry(), _library_entry(library_package_sha256)],
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
        package_sha256=compute_installed_source_sha256(Path(manifest.plugin_dir)),
        installed_package_sha256=compute_installed_package_sha256(
            Path(manifest.plugin_dir)
        ),
    )


def _resolve_with_installed_library(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    kind: str = "library",
    version: str = "1.0.0",
    configure=None,
    prepare_installed=None,
    mutate_installed=None,
) -> list[PluginRegistryEntry]:
    manifest = _library_manifest(tmp_path, kind=kind, version=version)
    plugin_dir = Path(manifest.plugin_dir)
    if prepare_installed is not None:
        prepare_installed(plugin_dir)
    package_sha256 = compute_installed_source_sha256(plugin_dir)
    snapshot = _snapshot(library_package_sha256=package_sha256)
    state = PluginPackageState(
        manifest=manifest,
        enabled=True,
        trusted=True,
    )
    config = AppConfig()
    package_config = _valid_config(manifest, snapshot)
    if configure is not None:
        package_config = configure(package_config)
    if mutate_installed is not None:
        mutate_installed(plugin_dir)
    config.plugins.packages["shared-library"] = package_config
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: tmp_path)
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
            lambda config: config.model_copy(update={"package_sha256": None}),
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


def test_changed_installed_dependency_content_cannot_satisfy_dependency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def prepare_installed(plugin_dir: Path) -> None:
        dependency_module = plugin_dir / ".deps" / "dependency" / "module.py"
        dependency_module.parent.mkdir(parents=True)
        dependency_module.write_text("VALUE = 1\n", encoding="utf-8")

    def mutate_installed(plugin_dir: Path) -> None:
        dependency_module = plugin_dir / ".deps" / "dependency" / "module.py"
        dependency_module.write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(PluginDependencyConflictError):
        _resolve_with_installed_library(
            monkeypatch,
            tmp_path,
            prepare_installed=prepare_installed,
            mutate_installed=mutate_installed,
        )
