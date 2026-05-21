"""Tests for manifest-driven default settings in ConfigPluginLayoutMixin.

The dual-rail seed mechanism is:

1. Manifest defaults (``[plugin.default_settings]`` in each plugin's
   ``plugin.toml``) take precedence.
2. Hardcoded defaults in :meth:`ConfigPluginLayoutMixin._default_plugin_settings_map`
   are the legacy fallback.

These tests exercise both rails and the failure modes (missing/invalid TOML).
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


# Most builtin plugins have migrated their defaults into their plugin.toml
# manifest, leaving the hardcoded map nearly empty. The fallback-rail tests
# below inject a synthetic hardcoded entry via monkeypatch so the dual-rail
# behavior stays exercised regardless of how many plugins remain in the map.
_FAKE_HARDCODED_DEFAULTS = {
    "core-tools": {},
    "photo-library": {
        "sensors": {
            "photo_library": {
                "enabled": False,
                "sync_mode": "manual",
                "sync_interval_minutes": 60,
            }
        }
    },
}


def _patch_hardcoded_map(monkeypatch) -> None:
    """Force ``_default_plugin_settings_map`` to a deterministic synthetic value."""
    from magi.config.plugin_layout import ConfigPluginLayoutMixin

    monkeypatch.setattr(
        ConfigPluginLayoutMixin,
        "_default_plugin_settings_map",
        lambda self: dict(_FAKE_HARDCODED_DEFAULTS),
    )


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


def test_hardcoded_map_fallback_when_manifest_lacks_default_settings(
    tmp_path: Path, monkeypatch
) -> None:
    """Plugin in hardcoded map but with no manifest defaults uses the map."""
    _patch_config_paths(monkeypatch, tmp_path)
    _patch_hardcoded_map(monkeypatch)
    plugins_dir = tmp_path / "config" / "plugins"
    manifest_path = tmp_path / "photo_lib" / "plugin.toml"
    _write_manifest(
        manifest_path,
        """
[plugin]
id = "photo-library"
name = "Photo Library"
version = "0.1.0"
""".strip(),
    )
    _seed_index(
        plugins_dir,
        {
            "photo-library": {
                "enabled": False,
                "trusted": True,
                "source": "builtin",
                "manifest_path": str(manifest_path),
            }
        },
    )

    ConfigLoader().load()

    settings_file = plugins_dir / "photo-library.yaml"
    data = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
    # Hardcoded map ships photo-library defaults under sensors.photo_library
    assert "sensors" in data
    assert "photo_library" in data["sensors"]
    assert data["sensors"]["photo_library"]["sync_mode"] == "manual"


def test_manifest_defaults_win_over_hardcoded_map(tmp_path: Path, monkeypatch) -> None:
    """Plugin present in BOTH map and manifest: manifest wins."""
    _patch_config_paths(monkeypatch, tmp_path)
    _patch_hardcoded_map(monkeypatch)
    plugins_dir = tmp_path / "config" / "plugins"
    manifest_path = tmp_path / "photo_lib" / "plugin.toml"
    _write_manifest(
        manifest_path,
        """
[plugin]
id = "photo-library"
name = "Photo Library"
version = "0.1.0"

[plugin.default_settings.sensors.photo_library]
enabled = true
sync_mode = "interval"
sync_interval_minutes = 7
""".strip(),
    )
    _seed_index(
        plugins_dir,
        {
            "photo-library": {
                "enabled": True,
                "trusted": True,
                "source": "builtin",
                "manifest_path": str(manifest_path),
            }
        },
    )

    ConfigLoader().load()

    settings_file = plugins_dir / "photo-library.yaml"
    data = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
    sensor = data["sensors"]["photo_library"]
    # Manifest values, not the hardcoded ones (which would have enabled=False
    # and sync_mode="manual" / sync_interval_minutes=60).
    assert sensor["enabled"] is True
    assert sensor["sync_mode"] == "interval"
    assert sensor["sync_interval_minutes"] == 7
    # And manifest-only keys are NOT augmented with hardcoded keys: this is a
    # full-replace, not a merge.
    assert set(sensor.keys()) == {"enabled", "sync_mode", "sync_interval_minutes"}


def test_no_yaml_written_when_neither_manifest_nor_map_has_defaults(
    tmp_path: Path, monkeypatch
) -> None:
    """A plugin with no defaults from either rail does not get a YAML file."""
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


def test_invalid_toml_in_manifest_falls_back_to_hardcoded_map(
    tmp_path: Path, monkeypatch
) -> None:
    """Manifest with broken TOML must not raise; falls back to hardcoded map."""
    _patch_config_paths(monkeypatch, tmp_path)
    _patch_hardcoded_map(monkeypatch)
    plugins_dir = tmp_path / "config" / "plugins"
    manifest_path = tmp_path / "broken" / "plugin.toml"
    _write_manifest(manifest_path, "this is not = valid TOML [[[")
    _seed_index(
        plugins_dir,
        {
            "photo-library": {
                "enabled": True,
                "trusted": True,
                "source": "builtin",
                "manifest_path": str(manifest_path),
            }
        },
    )

    # Should not raise.
    ConfigLoader().load()

    settings_file = plugins_dir / "photo-library.yaml"
    data = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
    # Hardcoded map default for photo-library.
    assert data["sensors"]["photo_library"]["sync_mode"] == "manual"


def test_missing_manifest_path_falls_back_to_hardcoded_map(
    tmp_path: Path, monkeypatch
) -> None:
    """manifest_path pointing to a non-existent file falls back silently."""
    _patch_config_paths(monkeypatch, tmp_path)
    _patch_hardcoded_map(monkeypatch)
    plugins_dir = tmp_path / "config" / "plugins"
    _seed_index(
        plugins_dir,
        {
            "photo-library": {
                "enabled": True,
                "trusted": True,
                "source": "builtin",
                "manifest_path": str(tmp_path / "does-not-exist" / "plugin.toml"),
            }
        },
    )

    ConfigLoader().load()

    settings_file = plugins_dir / "photo-library.yaml"
    data = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
    assert data["sensors"]["photo_library"]["sync_mode"] == "manual"
