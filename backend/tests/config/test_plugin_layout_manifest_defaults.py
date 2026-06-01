"""Tests for manifest-driven default settings in ConfigPluginLayoutMixin.

The seed mechanism is single-rail: each plugin's ``plugin.toml`` may declare a
``[plugin.default_settings]`` table, and the host writes that dict to
``~/.magi/config/plugins/{plugin_id}.yaml`` on first run. There is no
hardcoded fallback in the backend — plugins are fully self-describing.

These tests exercise the happy path and the failure modes (missing manifest
file, invalid TOML, no ``default_settings`` key).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from magi.config.loader import ConfigLoader


def _patch_config_paths(monkeypatch, root: Path) -> None:
    config_dir = root / "config"
    data_dir = root / "data"
    config_file = config_dir / "agent.yaml"
    plugins_dir = config_dir / "plugins"
    index_file = plugins_dir / "index.yaml"

    monkeypatch.setattr("magi.config.loader.get_config_dir", lambda: config_dir)
    monkeypatch.setattr("magi.config.loader.get_config_file", lambda: config_file)
    monkeypatch.setattr("magi.config.loader.get_plugins_config_dir", lambda: plugins_dir)
    monkeypatch.setattr("magi.config.loader.get_plugins_index_file", lambda: index_file)
    monkeypatch.setattr(
        "magi.config.loader.get_plugin_settings_file",
        lambda plugin_id: plugins_dir / f"{plugin_id}.yaml",
    )
    monkeypatch.setattr("magi.config.loader.get_data_dir", lambda: data_dir)
    monkeypatch.setattr("magi.config.loader.get_example_config_file", lambda: root / "missing-example.yaml")
    monkeypatch.setattr("magi.config.loader.get_llm_config_file", lambda: config_dir / "llm.yaml")
    monkeypatch.setattr("magi.config.loader.get_lifecycle_config_file", lambda: config_dir / "lifecycle.yaml")
    monkeypatch.setattr(
        "magi.config.loader.get_lifecycle_example_config_file",
        lambda: root / "lifecycle.example.yaml",
    )
    monkeypatch.setattr("magi.config.loader.get_llm_provider_registry_file", lambda: root / "llm_providers.yaml")
    packaged_llm_registry = Path(__file__).resolve().parents[2] / "configs" / "llm_providers.yaml"
    (root / "llm_providers.yaml").write_text(packaged_llm_registry.read_text(encoding="utf-8"), encoding="utf-8")
    packaged_lifecycle = Path(__file__).resolve().parents[2] / "configs" / "lifecycle.example.yaml"
    (root / "lifecycle.example.yaml").write_text(packaged_lifecycle.read_text(encoding="utf-8"), encoding="utf-8")


def _seed_index(plugins_dir: Path, entries: Dict[str, Dict[str, Any]]) -> None:
    """Write ``plugins/index.yaml`` so the seed loop sees these packages."""
    plugins_dir.mkdir(parents=True, exist_ok=True)
    index_file = plugins_dir / "index.yaml"
    index_file.write_text(
        yaml.safe_dump({"packages": entries}, sort_keys=False),
        encoding="utf-8",
    )


def _write_manifest(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_manifest_default_settings_seed_plugin_yaml(tmp_path: Path, monkeypatch) -> None:
    """A plugin that ships [plugin.default_settings] gets that exact dict written."""
    _patch_config_paths(monkeypatch, tmp_path)
    plugins_dir = tmp_path / "config" / "plugins"
    manifest_path = tmp_path / "plugin_pkg" / "plugin.toml"
    _write_manifest(
        manifest_path,
        """
[plugin]
id = "screenshot_timeline"
name = "Screenshot Timeline"
version = "0.1.0"

[plugin.default_settings.sensors.timeline]
enabled = false
capture_scope = "hybrid"
ocr_level = "accurate"
""".strip(),
    )
    _seed_index(
        plugins_dir,
        {
            "screenshot_timeline": {
                "enabled": True,
                "trusted": True,
                "source": "external",
                "manifest_path": str(manifest_path),
            }
        },
    )

    ConfigLoader().load()

    settings_file = plugins_dir / "screenshot_timeline.yaml"
    data = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
    assert data == {
        "sensors": {
            "timeline": {
                "enabled": False,
                "capture_scope": "hybrid",
                "ocr_level": "accurate",
            }
        }
    }


def test_empty_default_settings_table_writes_empty_yaml(tmp_path: Path, monkeypatch) -> None:
    """A plugin with an empty [plugin.default_settings] table seeds an empty YAML.

    This is the core-tools case: the plugin declares the table to opt into
    the seed rail, but ships no actual defaults. The resulting file is an
    empty dict, which is functionally equivalent to no file at all.
    """
    _patch_config_paths(monkeypatch, tmp_path)
    plugins_dir = tmp_path / "config" / "plugins"
    manifest_path = tmp_path / "empty_pkg" / "plugin.toml"
    _write_manifest(
        manifest_path,
        """
[plugin]
id = "core-tools"
name = "Core Tools"
version = "1.0.0"

[plugin.default_settings]
""".strip(),
    )
    _seed_index(
        plugins_dir,
        {
            "core-tools": {
                "enabled": True,
                "trusted": True,
                "source": "builtin",
                "manifest_path": str(manifest_path),
            }
        },
    )

    ConfigLoader().load()

    settings_file = plugins_dir / "core-tools.yaml"
    assert settings_file.exists()
    data = yaml.safe_load(settings_file.read_text(encoding="utf-8"))
    # Empty TOML table -> empty dict (or None when YAML-dumped); both are
    # equivalent for the loader.
    assert data in ({}, None)


def test_no_yaml_written_when_manifest_omits_default_settings(
    tmp_path: Path, monkeypatch
) -> None:
    """A plugin whose manifest has no [plugin.default_settings] table gets no YAML."""
    _patch_config_paths(monkeypatch, tmp_path)
    plugins_dir = tmp_path / "config" / "plugins"
    manifest_path = tmp_path / "ghost_pkg" / "plugin.toml"
    _write_manifest(
        manifest_path,
        """
[plugin]
id = "ghost-plugin"
name = "Ghost Plugin"
version = "0.1.0"
""".strip(),
    )
    _seed_index(
        plugins_dir,
        {
            "ghost-plugin": {
                "enabled": True,
                "trusted": False,
                "source": "external",
                "manifest_path": str(manifest_path),
            }
        },
    )

    ConfigLoader().load()

    settings_file = plugins_dir / "ghost-plugin.yaml"
    assert not settings_file.exists()


def test_invalid_toml_in_manifest_skips_seeding_without_raising(
    tmp_path: Path, monkeypatch
) -> None:
    """Manifest with broken TOML must not raise; the plugin just gets no YAML."""
    _patch_config_paths(monkeypatch, tmp_path)
    plugins_dir = tmp_path / "config" / "plugins"
    manifest_path = tmp_path / "broken" / "plugin.toml"
    _write_manifest(manifest_path, "this is not = valid TOML [[[")
    _seed_index(
        plugins_dir,
        {
            "busted-plugin": {
                "enabled": True,
                "trusted": True,
                "source": "external",
                "manifest_path": str(manifest_path),
            }
        },
    )

    # Should not raise.
    ConfigLoader().load()

    settings_file = plugins_dir / "busted-plugin.yaml"
    assert not settings_file.exists()


def test_missing_manifest_path_skips_seeding(tmp_path: Path, monkeypatch) -> None:
    """manifest_path pointing to a non-existent file is silently skipped."""
    _patch_config_paths(monkeypatch, tmp_path)
    plugins_dir = tmp_path / "config" / "plugins"
    _seed_index(
        plugins_dir,
        {
            "missing-plugin": {
                "enabled": True,
                "trusted": True,
                "source": "external",
                "manifest_path": str(tmp_path / "does-not-exist" / "plugin.toml"),
            }
        },
    )

    ConfigLoader().load()

    settings_file = plugins_dir / "missing-plugin.yaml"
    assert not settings_file.exists()


def test_existing_plugin_yaml_is_not_overwritten(tmp_path: Path, monkeypatch) -> None:
    """If {plugin_id}.yaml already exists, the seed loop must not stomp it."""
    _patch_config_paths(monkeypatch, tmp_path)
    plugins_dir = tmp_path / "config" / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = tmp_path / "pkg" / "plugin.toml"
    _write_manifest(
        manifest_path,
        """
[plugin]
id = "user-plugin"
name = "User Plugin"
version = "0.1.0"

[plugin.default_settings.sensors.foo]
enabled = false
""".strip(),
    )

    # Pre-existing user settings — different from the manifest defaults.
    existing_settings = {"sensors": {"foo": {"enabled": True, "interval": 42}}}
    (plugins_dir / "user-plugin.yaml").write_text(
        yaml.safe_dump(existing_settings, sort_keys=False),
        encoding="utf-8",
    )
    _seed_index(
        plugins_dir,
        {
            "user-plugin": {
                "enabled": True,
                "trusted": True,
                "source": "external",
                "manifest_path": str(manifest_path),
            }
        },
    )

    ConfigLoader().load()

    data = yaml.safe_load((plugins_dir / "user-plugin.yaml").read_text(encoding="utf-8")) or {}
    assert data == existing_settings
