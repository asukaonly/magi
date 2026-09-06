from __future__ import annotations

from pathlib import Path

import yaml

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
            f"plugins.packages.{plugin_id}.trusted": False,
            f"plugins.packages.{plugin_id}.source": "external",
        }
    )


def test_delete_metadata_does_not_restore_historical_builtin_defaults(tmp_path, monkeypatch):
    loader = _build_loader(tmp_path, monkeypatch)
    _save_external_plugin(loader, "calendar")
    assert loader.delete_plugin_package("calendar")
    assert loader.reload().plugins.packages == {}
    assert yaml.safe_load(loader._plugins_index_file.read_text()) == {"packages": {}}


def test_builtin_metadata_is_preserved(tmp_path, monkeypatch):
    loader = _build_loader(tmp_path, monkeypatch)
    assert loader.save(
        {
            "plugins.packages.core-tools.source": "builtin",
            "plugins.packages.core-tools.trusted": True,
        }
    )
    before = loader._plugins_index_file.read_bytes()
    assert loader.delete_plugin_package("core-tools") is False
    assert loader.delete_plugin_package("missing") is False
    assert loader._plugins_index_file.read_bytes() == before


def test_delete_metadata_ignores_orphan_settings_files(tmp_path, monkeypatch):
    loader = _build_loader(tmp_path, monkeypatch)
    _save_external_plugin(loader)
    orphan = loader._plugins_index_file.parent / "demo-plugin.yaml"
    orphan.write_text("secret: do-not-migrate\n")
    assert loader.delete_plugin_package("demo-plugin")
    assert orphan.read_text() == "secret: do-not-migrate\n"
    assert loader.load().plugins.packages == {}


def test_delete_restores_index_when_reload_fails(tmp_path, monkeypatch):
    loader = _build_loader(tmp_path, monkeypatch)
    _save_external_plugin(loader)
    before = loader._plugins_index_file.read_bytes()

    def fail_reload():
        raise RuntimeError("configuration reload failed")

    monkeypatch.setattr(loader, "load", fail_reload)
    assert loader.delete_plugin_package("demo-plugin") is False
    assert loader._plugins_index_file.read_bytes() == before


def test_delete_preserves_index_when_write_fails(tmp_path, monkeypatch):
    loader = _build_loader(tmp_path, monkeypatch)
    _save_external_plugin(loader)
    before = loader._plugins_index_file.read_bytes()

    def fail_write(path, data):
        raise OSError("disk unavailable")

    monkeypatch.setattr(loader, "_write_yaml_file", fail_write)
    assert loader.delete_plugin_package("demo-plugin") is False
    assert loader._plugins_index_file.read_bytes() == before
    assert "demo-plugin" in loader.load().plugins.packages


def test_null_metadata_is_not_package_deletion(tmp_path, monkeypatch):
    loader = _build_loader(tmp_path, monkeypatch)
    _save_external_plugin(loader)
    assert loader.save({"plugins.packages.demo-plugin": None}) is False
    assert "demo-plugin" in loader.load().plugins.packages
