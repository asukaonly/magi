from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from magi.config.plugin_models import PluginSettings
from magi.plugins import package_files
from magi.plugins.contracts import PluginManifest
from magi.plugins.package_identity import (
    compute_installed_package_sha256,
    compute_package_sha256,
)
from magi.plugins.package_integrity import (
    has_registry_install_record,
    is_verified_registry_package,
    package_identity_error,
)

PACKAGE_SHA256 = "a" * 64
REGISTRY_URL = "https://example.test/registry.json"
REPOSITORY_URL = "https://example.test/plugins.git"


def _managed_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    plugin_id: str = "example-plugin",
) -> PluginManifest:
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: tmp_path)
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir()
    manifest_path = plugin_dir / "plugin.toml"
    manifest_path.write_text(
        f'[plugin]\nprotocol_version = 2\nmin_sdk_version = "0.2.0"\nexecution_mode = "trusted_process"\nid = "{plugin_id}"\nname = "Example"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text("VALUE = 1\n", encoding="utf-8")
    return PluginManifest(
        id=plugin_id,
        name="Example",
        version="1.0.0",
        source="external",
        plugin_dir=str(plugin_dir),
        manifest_path=str(manifest_path),
    )


def _managed_settings(
    manifest: PluginManifest,
    *,
    install_origin: str,
    package_sha256: str | None,
    installed_package_sha256: str | None,
) -> PluginSettings:
    return PluginSettings(
        trusted=True,
        source="external",
        manifest_path=manifest.manifest_path,
        install_origin=install_origin,
        registry_source=REGISTRY_URL if install_origin == "registry" else None,
        registry_repo_url=REPOSITORY_URL if install_origin == "registry" else None,
        package_sha256=package_sha256,
        installed_package_sha256=installed_package_sha256,
    )


def test_plugin_settings_uses_complete_package_identities() -> None:
    assert "package_sha256" in PluginSettings.model_fields
    assert "installed_package_sha256" in PluginSettings.model_fields
    assert "dependency_package_sha256" in PluginSettings.model_fields
    assert "registry_entry_fingerprint" not in PluginSettings.model_fields
    assert "registry_manifest_fingerprint" not in PluginSettings.model_fields
    assert "dependency_entry_fingerprints" not in PluginSettings.model_fields

    configured = PluginSettings(
        package_sha256=PACKAGE_SHA256,
        installed_package_sha256="c" * 64,
        dependency_package_sha256={"shared-library": "b" * 64},
    )

    assert configured.package_sha256 == PACKAGE_SHA256
    assert configured.dependency_package_sha256 == {"shared-library": "b" * 64}


@pytest.mark.parametrize(
    "updates",
    [
        {"package_sha256": "a" * 63},
        {"package_sha256": "A" * 64},
        {"package_sha256": "g" * 64},
        {"installed_package_sha256": "c" * 63},
        {"dependency_package_sha256": {"shared-library": "b" * 63}},
    ],
)
def test_plugin_settings_rejects_invalid_package_digests(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PluginSettings.model_validate(updates)


@pytest.mark.parametrize("install_origin", ["registry", "upload", "local"])
def test_managed_install_recomputes_and_accepts_exact_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    install_origin: str,
) -> None:
    manifest = _managed_manifest(monkeypatch, tmp_path)
    plugin_dir = Path(manifest.plugin_dir)
    digest = compute_package_sha256(plugin_dir)
    installed_digest = compute_installed_package_sha256(plugin_dir)
    configured = _managed_settings(
        manifest,
        install_origin=install_origin,
        package_sha256=digest,
        installed_package_sha256=installed_digest,
    )

    assert package_identity_error(manifest, configured) is None
    assert is_verified_registry_package(manifest, configured) is (install_origin == "registry")


@pytest.mark.parametrize("install_origin", ["registry", "upload", "local"])
def test_managed_install_without_package_digest_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    install_origin: str,
) -> None:
    manifest = _managed_manifest(monkeypatch, tmp_path)
    configured = _managed_settings(
        manifest,
        install_origin=install_origin,
        package_sha256=None,
        installed_package_sha256="c" * 64,
    )

    error = package_identity_error(manifest, configured)

    assert error is not None
    assert "digest is missing" in error
    assert is_verified_registry_package(manifest, configured) is False


@pytest.mark.parametrize("install_origin", ["registry", "upload", "local"])
def test_managed_install_without_local_seal_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    install_origin: str,
) -> None:
    manifest = _managed_manifest(monkeypatch, tmp_path)
    configured = _managed_settings(
        manifest,
        install_origin=install_origin,
        package_sha256=compute_package_sha256(Path(manifest.plugin_dir)),
        installed_package_sha256=None,
    )

    error = package_identity_error(manifest, configured)

    assert error is not None
    assert "seal is missing" in error
    assert is_verified_registry_package(manifest, configured) is False


def test_managed_external_package_without_install_origin_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = _managed_manifest(monkeypatch, tmp_path)
    configured = PluginSettings(
        trusted=True,
        source="external",
        manifest_path=manifest.manifest_path,
    )

    error = package_identity_error(manifest, configured)

    assert error is not None
    assert "installation origin is missing" in error


def test_explicit_local_managed_package_requires_a_seal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = _managed_manifest(monkeypatch, tmp_path)
    configured = PluginSettings(
        trusted=True,
        source="external",
        manifest_path=manifest.manifest_path,
        install_origin="local",
    )

    assert "digest is missing" in package_identity_error(manifest, configured)


def test_legacy_registry_fingerprints_do_not_verify_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = _managed_manifest(monkeypatch, tmp_path)
    with pytest.raises(ValidationError, match="Extra inputs") as error:
        PluginSettings.model_validate(
            {
                "trusted": True,
                "source": "external",
                "manifest_path": manifest.manifest_path,
                "install_origin": "registry",
                "registry_source": REGISTRY_URL,
                "registry_repo_url": REPOSITORY_URL,
                "registry_entry_fingerprint": "legacy-entry",
                "registry_manifest_fingerprint": "legacy-manifest",
                "dependency_entry_fingerprints": {"shared-library": "legacy-dependency"},
            }
        )
    assert {item["loc"] for item in error.value.errors()} == {
        ("registry_entry_fingerprint",),
        ("registry_manifest_fingerprint",),
        ("dependency_entry_fingerprints",),
    }


def test_registry_package_requires_persisted_source_urls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = _managed_manifest(monkeypatch, tmp_path)
    plugin_dir = Path(manifest.plugin_dir)
    digest = compute_package_sha256(plugin_dir)
    configured = _managed_settings(
        manifest,
        install_origin="registry",
        package_sha256=digest,
        installed_package_sha256=compute_installed_package_sha256(plugin_dir),
    )
    configured.registry_source = None

    error = package_identity_error(manifest, configured)

    assert error is not None
    assert "source is missing" in error
    assert is_verified_registry_package(manifest, configured) is False


def test_managed_install_rejects_changed_package_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = _managed_manifest(monkeypatch, tmp_path)
    plugin_dir = Path(manifest.plugin_dir)
    digest = compute_package_sha256(plugin_dir)
    configured = _managed_settings(
        manifest,
        install_origin="registry",
        package_sha256=digest,
        installed_package_sha256=compute_installed_package_sha256(plugin_dir),
    )
    (Path(manifest.plugin_dir) / "plugin.py").write_text("VALUE = 2\n", encoding="utf-8")

    error = package_identity_error(manifest, configured)

    assert has_registry_install_record(manifest, configured) is True
    assert error is not None
    assert "integrity check failed" in error
    assert is_verified_registry_package(manifest, configured) is False


@pytest.mark.parametrize(
    "dependency_file",
    [
        "module.py",
        "native.so",
        "native.dylib",
        "native.pyd",
    ],
)
def test_managed_install_rejects_changed_dependency_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dependency_file: str,
) -> None:
    manifest = _managed_manifest(monkeypatch, tmp_path)
    plugin_dir = Path(manifest.plugin_dir)
    digest = compute_package_sha256(plugin_dir)
    dependency_path = plugin_dir / ".deps" / "dependency" / dependency_file
    dependency_path.parent.mkdir(parents=True)
    dependency_path.write_bytes(b"original")
    configured = _managed_settings(
        manifest,
        install_origin="registry",
        package_sha256=digest,
        installed_package_sha256=compute_installed_package_sha256(plugin_dir),
    )

    dependency_path.write_bytes(b"changed")

    error = package_identity_error(manifest, configured)

    assert error is not None
    assert "integrity check failed" in error
    assert is_verified_registry_package(manifest, configured) is False


def test_installed_mode_ignores_only_host_generated_runtime_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = _managed_manifest(monkeypatch, tmp_path)
    plugin_dir = Path(manifest.plugin_dir)
    digest = compute_package_sha256(plugin_dir)

    (plugin_dir / ".deps" / "dependency").mkdir(parents=True)
    (plugin_dir / ".deps" / "dependency" / "module.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    configured = _managed_settings(
        manifest,
        install_origin="upload",
        package_sha256=digest,
        installed_package_sha256=compute_installed_package_sha256(plugin_dir),
    )
    (plugin_dir / "__pycache__").mkdir()
    (plugin_dir / "__pycache__" / "plugin.cpython-313.pyc").write_bytes(b"cache")
    (plugin_dir / "nested" / "__pycache__").mkdir(parents=True)
    (plugin_dir / "nested" / "__pycache__" / "module.pyo").write_bytes(b"cache")

    assert package_identity_error(manifest, configured) is None

    (plugin_dir / "unexpected.txt").write_text("changed\n", encoding="utf-8")
    assert package_identity_error(manifest, configured) is not None


def test_builtin_and_unmanaged_dev_packages_do_not_require_managed_digest(
    tmp_path: Path,
) -> None:
    builtin_manifest = PluginManifest(
        id="builtin-plugin",
        name="Builtin",
        version="1.0.0",
        source="builtin",
    )
    assert (
        package_identity_error(
            builtin_manifest,
            PluginSettings(source="builtin", install_origin="builtin"),
        )
        is None
    )

    plugin_dir = tmp_path / "local-plugin"
    plugin_dir.mkdir()
    manifest_path = plugin_dir / "plugin.toml"
    manifest_path.write_text("[plugin]\n", encoding="utf-8")
    local_manifest = PluginManifest(
        id="local-plugin",
        name="Local",
        version="1.0.0",
        source="external",
        plugin_dir=str(plugin_dir),
        manifest_path=str(manifest_path),
    )
    assert (
        package_identity_error(
            local_manifest,
            PluginSettings(
                source="external",
                manifest_path=str(manifest_path),
            ),
        )
        is None
    )
    assert is_verified_registry_package(local_manifest, PluginSettings()) is False
