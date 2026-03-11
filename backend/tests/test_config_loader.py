from __future__ import annotations

from pathlib import Path

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
    monkeypatch.setattr("magi.config.loader.get_plugin_settings_file", lambda plugin_id: plugins_dir / f"{plugin_id}.yaml")
    monkeypatch.setattr("magi.config.loader.get_data_dir", lambda: data_dir)
    monkeypatch.setattr("magi.config.loader.get_example_config_file", lambda: root / "missing-example.yaml")


def test_loader_migrates_inline_plugin_settings_to_split_files(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    agent_file = config_dir / "agent.yaml"
    agent_file.write_text(
        yaml.safe_dump(
            {
                "plugins": {
                    "scan_paths": ["plugins", "~/.magi/plugins"],
                    "packages": {
                        "core-timeline": {
                            "enabled": True,
                            "trusted": True,
                            "source": "builtin",
                            "settings": {
                                "sensors": {
                                    "browser_history": {
                                        "enabled": True,
                                        "sync_mode": "interval",
                                        "sync_interval_minutes": 45,
                                    }
                                }
                            },
                        }
                    },
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    loader = ConfigLoader()
    config = loader.load()

    migrated_agent = yaml.safe_load(agent_file.read_text(encoding="utf-8")) or {}
    index_file = tmp_path / "config" / "plugins" / "index.yaml"
    settings_file = tmp_path / "config" / "plugins" / "core-timeline.yaml"
    index_data = yaml.safe_load(index_file.read_text(encoding="utf-8")) or {}
    settings_data = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}

    assert "packages" not in migrated_agent.get("plugins", {})
    assert index_data["packages"]["core-timeline"]["enabled"] is True
    assert settings_data["sensors"]["browser_history"]["sync_interval_minutes"] == 45
    assert config.plugins.packages["core-timeline"].settings["sensors"]["browser_history"]["sync_interval_minutes"] == 45


def test_loader_save_routes_plugin_updates_to_split_files(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)

    loader = ConfigLoader()
    config = loader.load()
    assert config.plugins.packages["core-timeline"].enabled is True

    saved = loader.save(
        {
            "plugins.packages.core-timeline.enabled": False,
            "plugins.packages.core-timeline.settings.sensors.browser_history.sync_interval_minutes": 90,
            "tools.weather.default_provider": "qweather",
        }
    )

    agent_data = yaml.safe_load((tmp_path / "config" / "agent.yaml").read_text(encoding="utf-8")) or {}
    index_data = yaml.safe_load((tmp_path / "config" / "plugins" / "index.yaml").read_text(encoding="utf-8")) or {}
    settings_data = yaml.safe_load((tmp_path / "config" / "plugins" / "core-timeline.yaml").read_text(encoding="utf-8")) or {}

    assert saved is True
    assert "packages" not in agent_data.get("plugins", {})
    assert agent_data["tools"]["weather"]["default_provider"] == "qweather"
    assert index_data["packages"]["core-timeline"]["enabled"] is False
    assert settings_data["sensors"]["browser_history"]["sync_interval_minutes"] == 90
    assert loader.load().plugins.packages["core-timeline"].enabled is False
    assert loader.load().plugins.packages["core-timeline"].settings["sensors"]["browser_history"]["sync_interval_minutes"] == 90
