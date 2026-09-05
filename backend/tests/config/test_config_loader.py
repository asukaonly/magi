from __future__ import annotations

import enum
import importlib
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from magi.config import loader as config_loader
from magi.config import loader_file_ops
from magi.utils.diagnostic_logging import (
    full_content_logging_enabled,
    set_full_content_logging_enabled,
)
from magi.config.loader import ConfigLoader
from magi.config.models import NetworkProxySettings, PluginsSettings, ProxyType
from magi.utils.log_redaction import MASKED_LOG_VALUE, redact_log_text


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
    monkeypatch.setattr("magi.config.loader.get_lifecycle_config_file", lambda: config_dir / "lifecycle.yaml")
    monkeypatch.setattr("magi.config.loader.get_lifecycle_example_config_file", lambda: root / "lifecycle.example.yaml")
    monkeypatch.setattr("magi.config.loader.get_llm_provider_registry_file", lambda: root / "llm_providers.yaml")
    packaged_llm_registry = Path(__file__).resolve().parents[2] / "configs" / "llm_providers.yaml"
    (root / "llm_providers.yaml").write_text(packaged_llm_registry.read_text(encoding="utf-8"), encoding="utf-8")
    packaged_lifecycle = Path(__file__).resolve().parents[2] / "configs" / "lifecycle.example.yaml"
    (root / "lifecycle.example.yaml").write_text(packaged_lifecycle.read_text(encoding="utf-8"), encoding="utf-8")


# Manifest-driven loader tests use repository-owned fixtures so their inputs
# cannot drift with a separately checked out plugin repository.
_PLUGIN_MANIFEST_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "plugin_manifests"
_PLUGIN_MANIFEST_DIRS = {
    "photo_library_core": "photo_library_core",
    "apple-photos": "apple-photos",
    "local-photos": "local-photos",
    "chrome-history": "chrome-history",
    "calendar": "calendar",
    "git-activity": "git-activity",
    "screen-time": "screen-time",
    "system-media": "system-media",
    "terminal-history": "terminal-history",
}


def _fixture_manifest_path(plugin_id: str) -> Path:
    manifest = (
        _PLUGIN_MANIFEST_FIXTURE_ROOT
        / _PLUGIN_MANIFEST_DIRS[plugin_id]
        / "plugin.toml"
    )
    assert manifest.is_file(), f"Missing plugin manifest fixture for {plugin_id}"
    return manifest


def test_l3_settings_round_trip_without_ineffective_summary_controls(tmp_path, monkeypatch):
    from magi.api.routers.config_response_builders import build_memory_config
    from magi.api.routers.config_schemas import SystemConfigModel
    from magi.api.routers.config_update_paths import _memory_update_paths
    from magi.config.introspection import list_app_config_specs

    _patch_config_paths(monkeypatch, tmp_path)
    loader = ConfigLoader()
    runtime = loader.load()
    proposed = SystemConfigModel(memory=build_memory_config({}, runtime))
    proposed.memory.l3.retention_days = 90
    proposed.memory.l3.llm_summary_enabled = False
    proposed.memory.l3.temporal_llm_timeout_seconds = 4.5
    proposed.memory.l3.temporal_llm_min_event_count = 5
    updates = _memory_update_paths(proposed)
    assert loader.save(updates) is True

    refreshed = loader.load()
    assert build_memory_config({}, refreshed).l3 == proposed.memory.l3
    assert refreshed.agent.memory.l3.maintenance_interval_seconds == runtime.agent.memory.l3.maintenance_interval_seconds
    persisted = yaml.safe_load((tmp_path / "config" / "agent.yaml").read_text())
    assert persisted["agent"]["memory"]["l3"] == proposed.memory.l3.model_dump()
    specs = {spec.path for spec in list_app_config_specs(prefix="")}
    for field in ("summary_interval_minutes", "digest_enabled", "digest_interval_hours"):
        assert field not in refreshed.agent.memory.l3.model_dump()
        assert f"agent.memory.l3.{field}" not in updates
        assert f"agent.memory.l3.{field}" not in specs


def _seed_fixture_manifest_paths(plugins_dir: Path) -> None:
    """Write an index that points builtin packages at fixed manifest fixtures."""
    plugins_dir.mkdir(parents=True, exist_ok=True)
    packages: Dict[str, Dict[str, Any]] = {}
    for plugin_id in _PLUGIN_MANIFEST_DIRS:
        packages[plugin_id] = {"manifest_path": str(_fixture_manifest_path(plugin_id))}
    (plugins_dir / "index.yaml").write_text(
        yaml.safe_dump({"packages": packages}, sort_keys=False),
        encoding="utf-8",
    )


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
                        "local-photos": {
                            "enabled": True,
                            "trusted": True,
                            "source": "builtin",
                            "settings": {
                                "sensors": {
                                    "photo_library_directory": {
                                        "enabled": True,
                                        "sync_mode": "interval",
                                        "sync_interval_minutes": 90,
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
    settings_file = tmp_path / "config" / "plugins" / "local-photos.yaml"
    index_data = yaml.safe_load(index_file.read_text(encoding="utf-8")) or {}
    settings_data = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}

    assert "packages" not in migrated_agent.get("plugins", {})
    assert index_data["packages"]["local-photos"]["enabled"] is True
    assert settings_data["sensors"]["photo_library_directory"]["sync_interval_minutes"] == 90
    assert (
        config.plugins.packages["local-photos"]
        .settings["sensors"]["photo_library_directory"]["sync_interval_minutes"]
        == 90
    )


def test_loader_save_routes_plugin_updates_to_split_files(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)

    loader = ConfigLoader()
    config = loader.load()
    assert config.plugins.packages["local-photos"].enabled is True

    saved = loader.save(
        {
            "plugins.packages.local-photos.enabled": False,
            (
                "plugins.packages.local-photos.settings.sensors."
                "photo_library_directory.sync_interval_minutes"
            ): 120,
            "tools.weather.default_provider": "qweather",
        }
    )

    agent_data = yaml.safe_load((tmp_path / "config" / "agent.yaml").read_text(encoding="utf-8")) or {}
    index_data = yaml.safe_load((tmp_path / "config" / "plugins" / "index.yaml").read_text(encoding="utf-8")) or {}
    settings_data = (
        yaml.safe_load(
            (tmp_path / "config" / "plugins" / "local-photos.yaml").read_text(encoding="utf-8")
        )
        or {}
    )

    assert saved is True
    assert "packages" not in agent_data.get("plugins", {})
    assert agent_data["tools"]["weather"]["default_provider"] == "qweather"
    assert index_data["packages"]["local-photos"]["enabled"] is False
    assert settings_data["sensors"]["photo_library_directory"]["sync_interval_minutes"] == 120
    assert loader.load().plugins.packages["local-photos"].enabled is False
    assert (
        loader.load()
        .plugins.packages["local-photos"]
        .settings["sensors"]["photo_library_directory"]["sync_interval_minutes"]
        == 120
    )


def test_loader_refreshes_diagnostic_policy_and_known_secrets_immediately(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_config_paths(monkeypatch, tmp_path)
    loader = ConfigLoader()
    loader.load()

    saved = loader.save(
        {
            "diagnostics.full_content_logging_enabled": False,
            "network.password": "loader-secret-password",
        }
    )

    assert saved is True
    assert loader.load().diagnostics.full_content_logging_enabled is False
    assert full_content_logging_enabled() is False
    assert (
        redact_log_text("failed with loader-secret-password")
        == f"failed with {MASKED_LOG_VALUE}"
    )
    set_full_content_logging_enabled(True)


def test_loader_save_rejects_invalid_config_without_writing(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)

    loader = ConfigLoader()
    config = loader.load()
    agent_file = tmp_path / "config" / "agent.yaml"
    original_yaml = agent_file.read_text(encoding="utf-8")

    saved = loader.save({"network.proxy_type": "none"})

    assert config.network.proxy_type == ProxyType.HTTP
    assert saved is False
    assert agent_file.read_text(encoding="utf-8") == original_yaml
    assert loader.load().network.proxy_type == ProxyType.HTTP


def test_get_user_preference_loads_runtime_config_when_global_loader_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    importlib.reload(config_loader)
    _patch_config_paths(monkeypatch, tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "agent.yaml").write_text(
        yaml.safe_dump({"preferences": {"language": "en"}}, sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_loader, "_loader", None)

    assert config_loader.get_user_preference("language", None) == "en"


def test_network_proxy_url_includes_encoded_credentials() -> None:
    settings = NetworkProxySettings(
        enabled=True,
        proxy_type=ProxyType.HTTP,
        host="proxy.example.test",
        port=8080,
        username="magi user",
        password="pa:ss@word",
    )

    assert settings.proxy_url() == "http://magi%20user:pa%3Ass%40word@proxy.example.test:8080"


def test_loader_default_photo_sources_follow_independent_plugin_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_config_paths(monkeypatch, tmp_path)
    _seed_fixture_manifest_paths(tmp_path / "config" / "plugins")

    loader = ConfigLoader()
    config = loader.load()

    assert "core-timeline" not in config.plugins.packages
    assert "photo-library" not in config.plugins.packages

    core_package = config.plugins.packages["photo_library_core"]
    apple_package = config.plugins.packages["apple-photos"]
    local_package = config.plugins.packages["local-photos"]

    for package in (core_package, apple_package, local_package):
        assert package.enabled is True
        assert package.trusted is True
        assert package.source == "builtin"

    assert core_package.settings == {}

    apple_sensors = apple_package.settings["sensors"]
    local_sensors = local_package.settings["sensors"]
    assert set(apple_sensors) == {"photo_library_apple_photos"}
    assert set(local_sensors) == {"photo_library_directory"}
    assert apple_sensors["photo_library_apple_photos"]["enabled"] is False
    assert apple_sensors["photo_library_apple_photos"]["source_mode"] == "apple_photos"
    assert "source_paths" not in apple_sensors["photo_library_apple_photos"]
    assert local_sensors["photo_library_directory"]["enabled"] is False
    assert local_sensors["photo_library_directory"]["source_mode"] == "directory"
    assert "photos_library_path" not in local_sensors["photo_library_directory"]


def test_plugin_model_defaults_use_independent_photo_packages() -> None:
    packages = PluginsSettings().packages

    assert "photo-library" not in packages
    for plugin_id in ("photo_library_core", "apple-photos", "local-photos"):
        package = packages[plugin_id]
        assert package.enabled is True
        assert package.trusted is True
        assert package.source == "builtin"


def test_loader_enables_builtin_sensor_plugins_while_leaving_sources_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_config_paths(monkeypatch, tmp_path)
    _seed_fixture_manifest_paths(tmp_path / "config" / "plugins")

    loader = ConfigLoader()
    config = loader.load()

    for plugin_id, source_name in (
        ("calendar", "calendar"),
        ("git-activity", "git_activity"),
        ("screen-time", "screen_time"),
        ("terminal-history", "terminal_history"),
    ):
        package = config.plugins.packages[plugin_id]
        assert package.enabled is True
        assert package.trusted is True
        assert package.settings["sensors"][source_name]["enabled"] is False

    assert "apple-health" not in config.plugins.packages

    screen_time_settings = config.plugins.packages["screen-time"].settings["sensors"]["screen_time"]
    assert screen_time_settings["sync_interval_minutes"] == 5
    assert "sync_interval_hours" not in screen_time_settings
    assert "default_retention_mode" not in screen_time_settings


def test_loader_migrates_legacy_disabled_chrome_history_plugin(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)
    config_dir = tmp_path / "config" / "plugins"
    config_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "agent.yaml").write_text("plugins:\n  scan_paths:\n    - plugins\n", encoding="utf-8")
    chrome_manifest = _fixture_manifest_path("chrome-history")
    (config_dir / "index.yaml").write_text(
        yaml.safe_dump(
            {
                "packages": {
                    "chrome-history": {
                        "enabled": False,
                        "trusted": False,
                        "source": "builtin",
                        "manifest_path": str(chrome_manifest),
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
    assert config.llm.providers == {}
    assert "auxiliary" in config.llm.selections
    assert "core" in config.llm.selections
    assert config.llm.selections["auxiliary"].provider_id == ""
    assert config.llm.selections["auxiliary"].model == ""
    assert config.llm.selections["core"].provider_id == ""
    assert config.llm.selections["core"].model == ""


def test_loader_ignores_llm_environment_overrides(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    loader = ConfigLoader()
    config = loader.load()

    assert config.llm.providers == {}
    assert config.llm.selections["auxiliary"].provider_id == ""
    assert config.llm.selections["auxiliary"].model == ""
    assert config.llm.selections["core"].provider_id == ""
    assert config.llm.selections["core"].model == ""


def test_loader_creates_llm_split_file_and_loads_default_llm_config(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)

    loader = ConfigLoader()
    config = loader.load()

    llm_file = tmp_path / "config" / "llm.yaml"
    llm_data = yaml.safe_load(llm_file.read_text(encoding="utf-8")) or {}

    assert llm_file.exists()
    assert llm_data == {}
    assert config.llm.providers == {}
    assert config.llm.selections["core"].provider_id == ""
    assert config.llm.selections["core"].model == ""


def test_loader_creates_lifecycle_split_file_and_loads_policy(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)

    loader = ConfigLoader()
    config = loader.load()

    lifecycle_file = tmp_path / "config" / "lifecycle.yaml"
    lifecycle_data = yaml.safe_load(lifecycle_file.read_text(encoding="utf-8")) or {}

    assert lifecycle_file.exists()
    assert lifecycle_data["lifecycle"]["runtime_trace"]["raw_retention_days"] == 7
    assert lifecycle_data["lifecycle"]["llm_usage"]["cache_observability"] == {
        "enabled": True,
        "retention_days": 30,
        "max_rows": 50000,
        "store_tool_names": True,
    }
    assert config.lifecycle.runtime_trace.raw_retention_days == 7
    assert config.lifecycle.llm_usage.cache_observability.enabled is True
    assert config.lifecycle.llm_usage.cache_observability.max_rows == 50_000
    assert config.lifecycle.message_queue.completed.raw_retention_hours == 24
    assert config.lifecycle.scheduler.executions.failed_retention_days == 60


def test_loader_save_routes_lifecycle_updates_to_split_file(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)

    loader = ConfigLoader()
    _ = loader.load()
    saved = loader.save(
        {
            "lifecycle.runtime_trace.raw_retention_days": 9,
            "lifecycle.message_queue.completed.raw_retention_hours": 12,
            "tools.weather.default_provider": "qweather",
        }
    )

    agent_data = yaml.safe_load((tmp_path / "config" / "agent.yaml").read_text(encoding="utf-8")) or {}
    lifecycle_data = yaml.safe_load((tmp_path / "config" / "lifecycle.yaml").read_text(encoding="utf-8")) or {}

    assert saved is True
    assert "lifecycle" not in agent_data
    assert lifecycle_data["lifecycle"]["runtime_trace"]["raw_retention_days"] == 9
    assert lifecycle_data["lifecycle"]["message_queue"]["completed"]["raw_retention_hours"] == 12
    assert loader.load().lifecycle.runtime_trace.raw_retention_days == 9
    assert loader.load().lifecycle.message_queue.completed.raw_retention_hours == 12


def test_loader_save_writes_llm_overrides_only(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)

    loader = ConfigLoader()
    _ = loader.load()
    saved = loader.save(
        {
            "llm.providers.openai.enabled": True,
            "llm.providers.openai.provider_type": "openai",
            "llm.providers.openai.display_name": "OpenAI",
            "llm.providers.openai.services.chat.api_key": "sk-test",
            "llm.providers.openai.services.chat.base_url": "https://api.openai.com/v1",
            "llm.selections.core.provider_id": "openai",
            "llm.selections.core.model": "gpt-5",
        }
    )

    llm_data = yaml.safe_load((tmp_path / "config" / "llm.yaml").read_text(encoding="utf-8")) or {}

    assert saved is True
    assert llm_data["providers"]["openai"]["enabled"] is True
    assert llm_data["providers"]["openai"]["provider_type"] == "openai"
    assert llm_data["providers"]["openai"]["services"]["chat"]["api_key"] == "sk-test"
    assert llm_data["providers"]["openai"]["services"]["chat"]["base_url"] == "https://api.openai.com/v1"
    assert llm_data["selections"]["core"]["provider_id"] == "openai"
    assert llm_data["selections"]["core"]["model"] == "gpt-5"
    assert "temperature" not in llm_data


def test_loader_reloads_after_external_llm_file_change(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)

    loader = ConfigLoader()
    config = loader.load()

    assert config.llm.providers == {}

    llm_file = tmp_path / "config" / "llm.yaml"
    llm_file.write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "openai": {
                        "enabled": True,
                        "provider_type": "openai",
                        "display_name": "OpenAI",
                        "model_metadata_overrides": {
                            "gpt-5.2": {
                                "capabilities": {
                                    "vision": True,
                                }
                            }
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    reloaded = loader.load()

    assert reloaded.llm.providers["openai"].model_metadata_overrides["gpt-5.2"].capabilities.vision is True


def test_loader_reuses_cached_config_without_re_running_ensure(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)

    loader = ConfigLoader()
    cached = loader.load()

    def _fail_if_called() -> None:
        raise AssertionError("_ensure_config_exists should not run when cached config is still valid")

    monkeypatch.setattr(loader, "_ensure_config_exists", _fail_if_called)

    reused = loader.load()

    assert reused is cached


def test_loader_reload_re_runs_ensure(tmp_path: Path, monkeypatch) -> None:
    _patch_config_paths(monkeypatch, tmp_path)

    loader = ConfigLoader()
    loader.load()

    ensure_calls = 0
    original_ensure = loader._ensure_config_exists

    def _counted_ensure() -> None:
        nonlocal ensure_calls
        ensure_calls += 1
        original_ensure()

    monkeypatch.setattr(loader, "_ensure_config_exists", _counted_ensure)

    reloaded = loader.reload()

    assert ensure_calls == 1
    assert reloaded is loader._config


def test_write_yaml_file_preserves_original_when_serialization_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """A serialization failure must not truncate or wipe the existing file.

    Regression: ``_write_yaml_file`` used ``open(path, 'w')`` (which truncates
    immediately) and then streamed ``safe_dump`` into it. When the payload held
    a value ``safe_dump`` could not represent (e.g. an enum smuggled in via a
    ``model_dump()`` without ``mode="json"``), it raised mid-write and left the
    real config file truncated to a few bytes. The write must be atomic: on
    failure the original contents survive untouched.
    """
    _patch_config_paths(monkeypatch, tmp_path)
    loader = ConfigLoader()

    target = tmp_path / "config" / "agent.yaml"
    loader._write_yaml_file(target, {"keep": "me", "count": 1})
    original = target.read_text(encoding="utf-8")
    assert original  # sanity: the good file is non-empty

    class _Unrepresentable(enum.Enum):
        VALUE = "value"

    with pytest.raises(Exception):
        loader._write_yaml_file(target, {"poisoned": _Unrepresentable.VALUE})

    assert target.read_text(encoding="utf-8") == original


def test_write_yaml_file_uses_independent_temp_files_for_concurrent_writers(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_config_paths(monkeypatch, tmp_path)
    target = tmp_path / "config" / "agent.yaml"
    loaders = (ConfigLoader(), ConfigLoader())
    payloads = ({"writer": "first"}, {"writer": "second"})
    replace_barrier = threading.Barrier(2)
    replace_sources: list[Path] = []
    sources_lock = threading.Lock()
    original_replace = loader_file_ops.os.replace

    def synchronized_replace(source: Path, destination: Path) -> None:
        with sources_lock:
            replace_sources.append(Path(source))
        replace_barrier.wait(timeout=5)
        original_replace(source, destination)

    monkeypatch.setattr(loader_file_ops.os, "replace", synchronized_replace)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(loader._write_yaml_file, target, payload)
            for loader, payload in zip(loaders, payloads, strict=True)
        ]
        for future in futures:
            future.result(timeout=5)

    assert len(set(replace_sources)) == 2
    assert yaml.safe_load(target.read_text(encoding="utf-8")) in payloads
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))


def test_write_yaml_file_cleans_only_its_temp_file_when_replace_fails(
    tmp_path: Path, monkeypatch
) -> None:
    _patch_config_paths(monkeypatch, tmp_path)
    loader = ConfigLoader()
    target = tmp_path / "config" / "agent.yaml"
    loader._write_yaml_file(target, {"keep": "original"})
    original = target.read_text(encoding="utf-8")
    unrelated_temp = target.parent / f".{target.name}.other-writer.tmp"
    unrelated_temp.write_text("owned elsewhere", encoding="utf-8")
    staged_paths: list[Path] = []

    def fail_replace(source: Path, _destination: Path) -> None:
        staged_paths.append(Path(source))
        raise OSError("simulated replace failure")

    monkeypatch.setattr(loader_file_ops.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        loader._write_yaml_file(target, {"new": "value"})

    assert target.read_text(encoding="utf-8") == original
    assert len(staged_paths) == 1
    assert not staged_paths[0].exists()
    assert unrelated_temp.read_text(encoding="utf-8") == "owned elsewhere"
