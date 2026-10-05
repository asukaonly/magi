from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.api.routers.plugins_common import _authoritative_official
from magi.config.plugin_models import PluginSettings
from magi.plugins.contracts import (
    PluginManifest,
    PluginPackageState,
    PluginRegistryEntry,
    PluginRegistryIndex,
)
from magi.plugins import install_service as install_service_module
from magi.plugins import package_files, package_integrity
from magi.plugins.install_service import (
    registry_source_matches_installed_package,
)
from magi.plugins.package_identity import (
    compute_installed_package_sha256,
    compute_installed_source_sha256,
)
from magi.plugins.registry_client import (
    DEFAULT_REGISTRY_URL,
    DEFAULT_REPO_URL,
    PluginRegistrySnapshot,
)
from magi.plugins.registry_provenance import registry_install_fingerprint


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


@pytest.mark.parametrize(
    "source,manifest_official,configured,expected",
    [
        ("builtin", True, None, True),
        ("builtin", False, None, False),
        ("external", True, None, False),
        ("external", False, PluginSettings(official=True), False),
        ("external", False, _cfg_with("calendar", True)["calendar"], False),
        ("external", True, _cfg_with("calendar", False)["calendar"], False),
    ],
)
def test_official_badge_requires_builtin_or_verified_registry_provenance(
    source, manifest_official, configured, expected
):
    manifest = _FakeManifest("calendar", source, manifest_official)
    packages = {} if configured is None else {"calendar": configured}
    assert _authoritative_official(manifest, packages=packages, trusted=True) is expected


@pytest.mark.parametrize(
    "registry_url,repo_url,expected",
    [
        (DEFAULT_REGISTRY_URL, DEFAULT_REPO_URL, True),
        ("https://mirror.example/registry.json", DEFAULT_REPO_URL, False),
        (DEFAULT_REGISTRY_URL, "https://github.com/example/mirror.git", False),
    ],
)
def test_canonical_managed_registry_package_can_be_official(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    registry_url: str,
    repo_url: str,
    expected: bool,
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
        trusted=True,
        source="external",
        manifest_path=str(manifest_path),
        official=True,
        install_origin="registry",
        registry_source=registry_url,
        registry_repo_url=repo_url,
        package_sha256=compute_installed_source_sha256(plugin_dir),
        installed_package_sha256=compute_installed_package_sha256(plugin_dir),
    )

    def fail_if_full_verification_runs(_plugin_dir: Path) -> None:
        raise AssertionError("Official badge must not scan plugin contents")

    monkeypatch.setattr(
        package_integrity,
        "purge_plugin_bytecode_caches",
        fail_if_full_verification_runs,
    )

    assert _authoritative_official(manifest, packages={"calendar": configured}) is False
    assert (
        _authoritative_official(
            manifest,
            packages={"calendar": configured},
            trusted=True,
        )
        is expected
    )


def _snapshot(*, official_source: bool) -> PluginRegistrySnapshot:
    entry = PluginRegistryEntry(
        plugin_id="calendar",
        name="Calendar",
        version="1.0.0",
        package_sha256="1" * 64,
        path="plugins/calendar",
        official=True,
    )
    registry_url = DEFAULT_REGISTRY_URL if official_source else "https://mirror.example/index.json"
    index = PluginRegistryIndex(
        plugins=[entry],
        registry_version="4",
        repo_url=DEFAULT_REPO_URL,
    )
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


def test_marketplace_source_projection_uses_last_verified_trust_without_scanning(
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
        trusted=True,
        source="external",
        manifest_path=str(manifest_path),
        official=True,
        install_origin="registry",
        registry_source=DEFAULT_REGISTRY_URL,
        registry_repo_url=DEFAULT_REPO_URL,
        package_sha256=compute_installed_source_sha256(plugin_dir),
        installed_package_sha256=compute_installed_package_sha256(plugin_dir),
    )
    config = SimpleNamespace(
        plugins=SimpleNamespace(packages={"calendar": configured}),
    )
    monkeypatch.setattr(install_service_module, "get_config", lambda: config)

    def fail_if_full_verification_runs(_plugin_dir: Path) -> None:
        raise AssertionError("Marketplace projection must not scan plugin contents")

    monkeypatch.setattr(
        package_integrity,
        "purge_plugin_bytecode_caches",
        fail_if_full_verification_runs,
    )
    snapshot = _snapshot(official_source=True)

    untrusted = PluginPackageState(manifest=manifest, trusted=False)
    trusted = PluginPackageState(manifest=manifest, trusted=True)

    assert registry_source_matches_installed_package(untrusted, snapshot) is False
    assert registry_source_matches_installed_package(trusted, snapshot) is True
