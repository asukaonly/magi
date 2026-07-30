from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from magi.config import delete_plugin_package
from magi.config import loader as config_loader
from magi.config.loader import ConfigLoader


def _build_loader(tmp_path: Path, monkeypatch) -> ConfigLoader:
    config_dir = tmp_path / "config"
    plugins_dir = config_dir / "plugins"
    llm_registry = tmp_path / "llm_providers.yaml"
    lifecycle_defaults = tmp_path / "lifecycle.example.yaml"
    backend_root = Path(__file__).resolve().parents[2]
    llm_registry.write_text(
        (backend_root / "configs" / "llm_providers.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    lifecycle_defaults.write_text(
        (backend_root / "configs" / "lifecycle.example.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    monkeypatch.setattr(config_loader, "get_config_dir", lambda: config_dir)
    monkeypatch.setattr(config_loader, "get_config_file", lambda: config_dir / "agent.yaml")
    monkeypatch.setattr(config_loader, "get_plugins_config_dir", lambda: plugins_dir)
    monkeypatch.setattr(
        config_loader,
        "get_plugins_index_file",
        lambda: plugins_dir / "index.yaml",
    )
    monkeypatch.setattr(
        config_loader,
        "get_plugin_settings_file",
        lambda plugin_id: plugins_dir / f"{plugin_id}.yaml",
    )
    monkeypatch.setattr(config_loader, "get_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(
        config_loader,
        "get_example_config_file",
        lambda: tmp_path / "missing-example.yaml",
    )
    monkeypatch.setattr(
        config_loader,
        "get_llm_config_file",
        lambda: config_dir / "llm.yaml",
    )
    monkeypatch.setattr(
        config_loader,
        "get_lifecycle_config_file",
        lambda: config_dir / "lifecycle.yaml",
    )
    monkeypatch.setattr(
        config_loader,
        "get_lifecycle_example_config_file",
        lambda: lifecycle_defaults,
    )
    monkeypatch.setattr(
        config_loader,
        "get_llm_provider_registry_file",
        lambda: llm_registry,
    )

    loader = ConfigLoader()
    loader.load()
    return loader


def _save_external_plugin(loader: ConfigLoader, plugin_id: str = "demo-plugin") -> None:
    assert loader.save(
        {
            f"plugins.packages.{plugin_id}.enabled": False,
            f"plugins.packages.{plugin_id}.trusted": False,
            f"plugins.packages.{plugin_id}.source": "sideload",
            f"plugins.packages.{plugin_id}.settings.endpoint": "https://example.test",
        }
    )


def test_loader_ignores_orphan_plugin_settings_files(tmp_path: Path, monkeypatch) -> None:
    loader = _build_loader(tmp_path, monkeypatch)
    plugins_dir = tmp_path / "config" / "plugins"
    (plugins_dir / "removed-plugin.yaml").write_text(
        "endpoint: https://stale.example.test\n",
        encoding="utf-8",
    )

    config = loader.reload()

    assert "removed-plugin" not in config.plugins.packages
    assert (plugins_dir / "removed-plugin.yaml").is_file()


def test_loader_rejects_settings_for_unindexed_plugin(tmp_path: Path, monkeypatch) -> None:
    loader = _build_loader(tmp_path, monkeypatch)

    saved = loader.save({"plugins.packages.missing-plugin.settings.token": "secret"})

    assert saved is False
    assert not (tmp_path / "config" / "plugins" / "missing-plugin.yaml").exists()
    assert "missing-plugin" not in loader.load().plugins.packages


def test_delete_plugin_package_removes_index_and_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    loader = _build_loader(tmp_path, monkeypatch)
    _save_external_plugin(loader)
    monkeypatch.setattr(config_loader, "_loader", loader)

    deleted = delete_plugin_package("demo-plugin")

    plugins_dir = tmp_path / "config" / "plugins"
    index_data = yaml.safe_load((plugins_dir / "index.yaml").read_text(encoding="utf-8"))
    assert deleted is True
    assert "demo-plugin" not in index_data["packages"]
    assert not (plugins_dir / "demo-plugin.yaml").exists()
    assert "demo-plugin" not in loader.load().plugins.packages


def test_delete_plugin_package_does_not_remove_builtin_defaults(
    tmp_path: Path,
    monkeypatch,
) -> None:
    loader = _build_loader(tmp_path, monkeypatch)
    plugins_dir = tmp_path / "config" / "plugins"
    index_before = (plugins_dir / "index.yaml").read_bytes()

    deleted = loader.delete_plugin_package("core-tools")

    assert deleted is False
    assert (plugins_dir / "index.yaml").read_bytes() == index_before
    assert loader.load().plugins.packages["core-tools"].source == "builtin"


def test_delete_external_package_with_builtin_id_restores_builtin_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    loader = _build_loader(tmp_path, monkeypatch)
    assert loader.save(
        {
            "plugins.packages.calendar.enabled": False,
            "plugins.packages.calendar.trusted": False,
            "plugins.packages.calendar.source": "external",
            "plugins.packages.calendar.manifest_path": "/user/plugins/calendar/plugin.toml",
            "plugins.packages.calendar.official": True,
            "plugins.packages.calendar.settings.endpoint": "https://example.test",
        }
    )
    plugins_dir = tmp_path / "config" / "plugins"

    deleted = loader.delete_plugin_package("calendar")

    index_data = yaml.safe_load((plugins_dir / "index.yaml").read_text(encoding="utf-8"))
    assert deleted is True
    assert index_data["packages"]["calendar"] == {
        "enabled": True,
        "trusted": True,
        "source": "builtin",
    }
    assert not (plugins_dir / "calendar.yaml").exists()
    restored = loader.load().plugins.packages["calendar"]
    assert restored.enabled is True
    assert restored.trusted is True
    assert restored.source == "builtin"
    assert restored.manifest_path is None
    assert restored.official is None


def test_builtin_id_restore_rolls_back_when_settings_cleanup_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    loader = _build_loader(tmp_path, monkeypatch)
    assert loader.save(
        {
            "plugins.packages.calendar.enabled": False,
            "plugins.packages.calendar.trusted": False,
            "plugins.packages.calendar.source": "external",
            "plugins.packages.calendar.settings.endpoint": "https://example.test",
        }
    )
    plugins_dir = tmp_path / "config" / "plugins"
    index_file = plugins_dir / "index.yaml"
    settings_file = plugins_dir / "calendar.yaml"
    index_before = index_file.read_bytes()
    settings_before = settings_file.read_bytes()

    def _fail_remove(_path: Path) -> None:
        raise PermissionError("settings file is busy")

    monkeypatch.setattr(loader, "_remove_plugin_settings_file", _fail_remove)

    deleted = loader.delete_plugin_package("calendar")

    assert deleted is False
    assert index_file.read_bytes() == index_before
    assert settings_file.read_bytes() == settings_before
    current = loader.load().plugins.packages["calendar"]
    assert current.source == "external"
    assert current.enabled is False


def test_delete_plugin_package_restores_files_when_settings_cleanup_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    loader = _build_loader(tmp_path, monkeypatch)
    _save_external_plugin(loader)
    plugins_dir = tmp_path / "config" / "plugins"
    index_file = plugins_dir / "index.yaml"
    settings_file = plugins_dir / "demo-plugin.yaml"
    index_before = index_file.read_bytes()
    settings_before = settings_file.read_bytes()

    def _fail_remove(_path: Path) -> None:
        raise PermissionError("settings file is busy")

    monkeypatch.setattr(loader, "_remove_plugin_settings_file", _fail_remove)

    deleted = loader.delete_plugin_package("demo-plugin")

    assert deleted is False
    assert index_file.read_bytes() == index_before
    assert settings_file.read_bytes() == settings_before
    assert "demo-plugin" in loader.load().plugins.packages


def test_delete_plugin_package_preserves_files_when_index_write_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    loader = _build_loader(tmp_path, monkeypatch)
    _save_external_plugin(loader)
    plugins_dir = tmp_path / "config" / "plugins"
    index_file = plugins_dir / "index.yaml"
    settings_file = plugins_dir / "demo-plugin.yaml"
    index_before = index_file.read_bytes()
    settings_before = settings_file.read_bytes()
    original_write = loader._write_yaml_file

    def _fail_deleted_index(path: Path, data: Dict[str, Any]) -> None:
        packages = data.get("packages", {})
        if path == index_file and "demo-plugin" not in packages:
            raise OSError("disk is read-only")
        original_write(path, data)

    monkeypatch.setattr(loader, "_write_yaml_file", _fail_deleted_index)

    deleted = loader.delete_plugin_package("demo-plugin")

    assert deleted is False
    assert index_file.read_bytes() == index_before
    assert settings_file.read_bytes() == settings_before
    assert "demo-plugin" in loader.load().plugins.packages


def test_delete_plugin_package_restores_deleted_settings_when_reload_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    loader = _build_loader(tmp_path, monkeypatch)
    _save_external_plugin(loader)
    plugins_dir = tmp_path / "config" / "plugins"
    index_file = plugins_dir / "index.yaml"
    settings_file = plugins_dir / "demo-plugin.yaml"
    index_before = index_file.read_bytes()
    settings_before = settings_file.read_bytes()

    def _fail_reload() -> None:
        raise RuntimeError("configuration reload failed")

    monkeypatch.setattr(loader, "load", _fail_reload)

    deleted = loader.delete_plugin_package("demo-plugin")

    assert deleted is False
    assert index_file.read_bytes() == index_before
    assert settings_file.read_bytes() == settings_before


def test_none_values_are_not_treated_as_package_deletion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    loader = _build_loader(tmp_path, monkeypatch)
    _save_external_plugin(loader)

    regular_saved = loader.save({"tools.weather.providers.qweather.api_key": None})
    package_saved = loader.save({"plugins.packages.demo-plugin": None})

    assert regular_saved is True
    assert package_saved is True
    assert loader.load().tools.weather.providers["qweather"].api_key is None
    assert "demo-plugin" in loader.load().plugins.packages
    assert (tmp_path / "config" / "plugins" / "demo-plugin.yaml").is_file()
