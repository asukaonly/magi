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
    monkeypatch.setattr("magi.config.loader.get_llm_config_file", lambda: config_dir / "llm.yaml")
    monkeypatch.setattr("magi.config.loader.get_llm_default_config_file", lambda: root / "llm.default.yaml")
    packaged_llm_defaults = Path(__file__).resolve().parents[2] / "configs" / "llm.default.yaml"
    (root / "llm.default.yaml").write_text(packaged_llm_defaults.read_text(encoding="utf-8"), encoding="utf-8")


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


def test_loader_migrates_legacy_disabled_chrome_history_plugin(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)
    config_dir = tmp_path / "config" / "plugins"
    config_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "agent.yaml").write_text("plugins:\n  scan_paths:\n    - plugins\n", encoding="utf-8")
    (config_dir / "index.yaml").write_text(
        yaml.safe_dump(
            {
                "packages": {
                    "chrome-history": {
                        "enabled": False,
                        "trusted": False,
                        "source": "builtin",
                        "manifest_path": "/Users/asuka/code/magi/plugins/chrome-history/plugin.toml",
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (config_dir / "chrome-history.yaml").write_text("{}", encoding="utf-8")

    loader = ConfigLoader()
    config = loader.load()
    index_data = yaml.safe_load((config_dir / "index.yaml").read_text(encoding="utf-8")) or {}
    settings_data = yaml.safe_load((config_dir / "chrome-history.yaml").read_text(encoding="utf-8")) or {}

    assert index_data["packages"]["chrome-history"]["enabled"] is True
    assert index_data["packages"]["chrome-history"]["trusted"] is True
    assert settings_data["sensors"]["chrome_history"]["enabled"] is False
    assert config.plugins.packages["chrome-history"].enabled is True
    assert config.plugins.packages["chrome-history"].settings["sensors"]["chrome_history"]["enabled"] is False


def test_loader_creates_default_scenario_llm_config(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)

    loader = ConfigLoader()
    config = loader.load()
    llm_data = yaml.safe_load((tmp_path / "config" / "llm.yaml").read_text(encoding="utf-8")) or {}

    assert llm_data == {}
    assert "openai" in config.llm.providers
    assert config.llm.providers["openai"].enabled is False
    assert "context_decider" in config.llm.selections
    assert "core" in config.llm.selections
    assert config.llm.selections["context_decider"].provider_id == ""
    assert config.llm.selections["context_decider"].model == ""
    assert config.llm.selections["core"].provider_id == ""
    assert config.llm.selections["core"].model == ""


def test_loader_ignores_llm_environment_overrides(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    loader = ConfigLoader()
    config = loader.load()

    assert config.llm.providers["openai"].api_key == ""
    assert config.llm.providers["openai"].enabled is False
    assert config.llm.selections["context_decider"].provider_id == ""
    assert config.llm.selections["context_decider"].model == ""
    assert config.llm.selections["core"].provider_id == ""
    assert config.llm.selections["core"].model == ""


def test_loader_creates_llm_split_file_and_loads_default_llm_config(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)
    (tmp_path / "llm.default.yaml").write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "openai": {
                        "enabled": False,
                        "provider_type": "openai",
                        "display_name": "OpenAI",
                        "api_key": "",
                        "base_url": "",
                        "api_format": None,
                        "custom_models": [],
                        "custom_default_model": None,
                    }
                },
                "selections": {
                    "context_decider": {
                        "provider_id": "",
                        "model": "",
                        "capability_override_enabled": False,
                        "capabilities": {
                            "vision": False,
                            "image_output": False,
                            "tool_calling": True,
                            "reasoning": True,
                            "embedding": False,
                        },
                        "limits": {"context_window": None, "max_output_tokens": None},
                        "provider_options": {},
                    },
                    "core": {
                        "provider_id": "",
                        "model": "",
                        "capability_override_enabled": False,
                        "capabilities": {
                            "vision": False,
                            "image_output": False,
                            "tool_calling": True,
                            "reasoning": True,
                            "embedding": False,
                        },
                        "limits": {"context_window": None, "max_output_tokens": None},
                        "provider_options": {},
                    },
                    "embedding": {
                        "provider_id": "",
                        "model": "",
                        "capability_override_enabled": False,
                        "capabilities": {
                            "vision": False,
                            "image_output": False,
                            "tool_calling": False,
                            "reasoning": False,
                            "embedding": True,
                        },
                        "limits": {"context_window": None, "max_output_tokens": None},
                        "provider_options": {},
                    },
                },
                "temperature": 0.7,
                "max_tokens": 4096,
                "timeout": 60,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    loader = ConfigLoader()
    config = loader.load()

    llm_file = tmp_path / "config" / "llm.yaml"
    llm_data = yaml.safe_load(llm_file.read_text(encoding="utf-8")) or {}

    assert llm_file.exists()
    assert llm_data == {}
    assert config.llm.providers["openai"].enabled is False
    assert config.llm.selections["core"].provider_id == ""
    assert config.llm.selections["core"].model == ""


def test_loader_save_writes_llm_overrides_only(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)
    (tmp_path / "llm.default.yaml").write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "openai": {
                        "enabled": False,
                        "provider_type": "openai",
                        "display_name": "OpenAI",
                        "api_key": "",
                        "base_url": "",
                        "api_format": None,
                        "custom_models": [],
                        "custom_default_model": None,
                    }
                },
                "selections": {
                    "context_decider": {
                        "provider_id": "",
                        "model": "",
                        "capability_override_enabled": False,
                        "capabilities": {
                            "vision": False,
                            "image_output": False,
                            "tool_calling": True,
                            "reasoning": True,
                            "embedding": False,
                        },
                        "limits": {"context_window": None, "max_output_tokens": None},
                        "provider_options": {},
                    },
                    "core": {
                        "provider_id": "",
                        "model": "",
                        "capability_override_enabled": False,
                        "capabilities": {
                            "vision": False,
                            "image_output": False,
                            "tool_calling": True,
                            "reasoning": True,
                            "embedding": False,
                        },
                        "limits": {"context_window": None, "max_output_tokens": None},
                        "provider_options": {},
                    },
                    "embedding": {
                        "provider_id": "",
                        "model": "",
                        "capability_override_enabled": False,
                        "capabilities": {
                            "vision": False,
                            "image_output": False,
                            "tool_calling": False,
                            "reasoning": False,
                            "embedding": True,
                        },
                        "limits": {"context_window": None, "max_output_tokens": None},
                        "provider_options": {},
                    },
                },
                "temperature": 0.7,
                "max_tokens": 4096,
                "timeout": 60,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    loader = ConfigLoader()
    _ = loader.load()
    saved = loader.save(
        {
            "llm.providers.openai.enabled": True,
            "llm.providers.openai.api_key": "sk-test",
            "llm.selections.core.provider_id": "openai",
            "llm.selections.core.model": "gpt-5",
        }
    )

    llm_data = yaml.safe_load((tmp_path / "config" / "llm.yaml").read_text(encoding="utf-8")) or {}

    assert saved is True
    assert llm_data["providers"]["openai"]["enabled"] is True
    assert llm_data["providers"]["openai"]["api_key"] == "sk-test"
    assert llm_data["selections"]["core"]["provider_id"] == "openai"
    assert llm_data["selections"]["core"]["model"] == "gpt-5"
    assert "temperature" not in llm_data
