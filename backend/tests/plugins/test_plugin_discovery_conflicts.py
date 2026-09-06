from __future__ import annotations

import logging
from pathlib import Path

from magi.plugins import discovery
from magi.plugins import package_files
from magi.config.models import PluginSettings


def _write_manifest(
    root: Path,
    directory: str,
    *,
    plugin_id: str,
    name: str,
    extra: str = "",
) -> Path:
    plugin_dir = root / directory
    plugin_dir.mkdir(parents=True)
    manifest_path = plugin_dir / "plugin.toml"
    manifest_path.write_text(
        (
            "[plugin]\n"
            'protocol_version = 2\nmin_sdk_version = "0.2.0"\nexecution_mode = "trusted_process"\n'
            f'id = "{plugin_id}"\n'
            f'name = "{name}"\n'
            'version = "1.0.0"\n'
            f"{extra}"
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_builtin_manifest_wins_even_when_external_root_is_listed_first(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    builtin_root = tmp_path / "builtin"
    external_root = tmp_path / "external"
    builtin_manifest = _write_manifest(
        builtin_root,
        "core",
        plugin_id="shared-id",
        name="Builtin",
    )
    ignored_manifest = _write_manifest(
        external_root,
        "shadow",
        plugin_id="shared-id",
        name="External Shadow",
        extra='icon = "asset:assets/missing.svg"\n',
    )
    _write_manifest(
        external_root,
        "valid",
        plugin_id="external-valid",
        name="External Valid",
    )
    monkeypatch.setattr(discovery, "default_builtin_root", lambda: builtin_root)

    with caplog.at_level(logging.WARNING, logger=discovery.__name__):
        manifests = discovery.discover_plugin_manifests([external_root, builtin_root])

    assert set(manifests) == {"shared-id", "external-valid"}
    assert manifests["shared-id"].source == "builtin"
    assert manifests["shared-id"].manifest_path == str(builtin_manifest)
    conflict = next(
        record
        for record in caplog.records
        if record.getMessage()
        == "Plugin manifest id conflict; keeping the first discovered package"
    )
    assert conflict.plugin_id == "shared-id"
    assert conflict.kept_manifest_path == str(builtin_manifest)
    assert conflict.ignored_manifest_path == str(ignored_manifest)
    assert conflict.kept_source == "builtin"
    assert conflict.ignored_source == "external"


def test_later_external_manifest_cannot_replace_existing_external_manifest(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    builtin_root = tmp_path / "builtin"
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_manifest = _write_manifest(
        first_root,
        "plugin",
        plugin_id="duplicate",
        name="First",
    )
    second_manifest = _write_manifest(
        second_root,
        "plugin",
        plugin_id="duplicate",
        name="Second",
    )
    monkeypatch.setattr(discovery, "default_builtin_root", lambda: builtin_root)

    with caplog.at_level(logging.WARNING, logger=discovery.__name__):
        manifests = discovery.discover_plugin_manifests([first_root, second_root])

    assert manifests["duplicate"].name == "First"
    assert manifests["duplicate"].manifest_path == str(first_manifest)
    conflict = next(record for record in caplog.records if record.plugin_id == "duplicate")
    assert conflict.kept_manifest_path == str(first_manifest)
    assert conflict.ignored_manifest_path == str(second_manifest)


def test_discovery_ignores_hidden_transaction_directories(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_manifest(
        root,
        ".plugins-demo-staging-deadbeef",
        plugin_id="demo",
        name="Hidden transaction",
    )

    manifests = discovery.discover_plugin_manifests([root])

    assert manifests == {}


def test_managed_package_wins_over_a_custom_scan_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    builtin_root = tmp_path / "builtin"
    managed_root = tmp_path / "managed"
    custom_root = tmp_path / "custom"
    managed_manifest = _write_manifest(
        managed_root,
        "shared-id",
        plugin_id="shared-id",
        name="Managed",
    )
    _write_manifest(
        custom_root,
        "shared-id",
        plugin_id="shared-id",
        name="Custom Shadow",
    )
    monkeypatch.setattr(discovery, "default_builtin_root", lambda: builtin_root)
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: managed_root)

    manifests = discovery.discover_plugin_manifests([custom_root, managed_root])

    assert manifests["shared-id"].name == "Managed"
    assert manifests["shared-id"].manifest_path == str(managed_manifest)


def test_managed_root_only_accepts_exact_direct_child_packages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    managed_root = tmp_path / "managed"
    managed_root.mkdir()
    (managed_root / "plugin.toml").write_text(
        '[plugin]\nprotocol_version = 2\nmin_sdk_version = "0.2.0"\nexecution_mode = "trusted_process"\nid = "root-manifest"\nname = "Root Manifest"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    _write_manifest(
        managed_root / "nested",
        "child",
        plugin_id="nested-child",
        name="Nested Child",
    )
    _write_manifest(
        managed_root,
        "wrong-directory",
        plugin_id="different-id",
        name="Mismatched Directory",
    )
    valid_manifest = _write_manifest(
        managed_root,
        "valid-package",
        plugin_id="valid-package",
        name="Valid Package",
    )
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: managed_root)

    manifests = discovery.discover_plugin_manifests([managed_root])

    assert set(manifests) == {"valid-package"}
    assert manifests["valid-package"].manifest_path == str(valid_manifest)


def test_identity_mismatch_cannot_inherit_settings_or_trust(tmp_path: Path) -> None:
    manifest_path = _write_manifest(
        tmp_path,
        "external-package",
        plugin_id="external-package",
        name="External Package",
    )
    manifest = discovery.load_plugin_manifest(manifest_path, source="external")

    states = discovery.build_package_states(
        manifests={manifest.plugin_id: manifest},
        packages={
            manifest.plugin_id: PluginSettings(
                trusted=True,
                source="builtin",
            )
        },
        previous_states={},
    )

    state = states[manifest.plugin_id]
    assert state.enabled is False
    assert state.trusted is False
    assert state.healthy is False
    assert state.current_settings == {}
    assert state.last_error == "Plugin source does not match its persisted installation record"
