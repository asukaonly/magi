from __future__ import annotations

import logging
from pathlib import Path

from magi.plugins import discovery


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
