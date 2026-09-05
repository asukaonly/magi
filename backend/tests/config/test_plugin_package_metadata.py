"""Installed package metadata never becomes a second connection settings store."""

import pytest
import yaml
from pydantic import ValidationError

from magi.config.plugin_models import PluginSettings, PluginsSettings
from test_plugin_package_deletion import _build_loader


def test_fresh_config_has_no_packages_or_per_package_settings(tmp_path, monkeypatch):
    loader = _build_loader(tmp_path, monkeypatch)
    assert PluginsSettings().packages == {}
    assert loader.load().plugins.packages == {}
    assert sorted(path.name for path in loader._plugins_index_file.parent.iterdir()) == [
        "index.yaml"
    ]


def test_metadata_round_trip_keeps_identity_trust_and_consent_only(tmp_path, monkeypatch):
    loader = _build_loader(tmp_path, monkeypatch)
    metadata = PluginSettings(
        trusted=True,
        source="external",
        install_origin="upload",
        registry_source="https://example.com/registry.json",
        registry_repo_url="https://example.com/plugins.git",
        manifest_path=str(tmp_path / "installed/plugin.toml"),
        package_sha256="a" * 64,
        installed_package_sha256="b" * 64,
        consented_capabilities=[{"capability": "network", "scope": ["example.com"]}],
    )
    assert loader.save(
        {
            f"plugins.packages.demo.{key}": value
            for key, value in metadata.model_dump(mode="json").items()
        }
    )
    assert loader.reload().plugins.packages == {"demo": metadata}
    persisted = yaml.safe_load(loader._plugins_index_file.read_text())
    assert persisted["packages"]["demo"] == metadata.model_dump(mode="json")
    assert "packages" not in yaml.safe_load(loader._config_file.read_text())["plugins"]
    assert not (loader._plugins_index_file.parent / "demo.yaml").exists()


@pytest.mark.parametrize("field,value", [("enabled", True), ("settings", {}), ("trusted", "yes")])
def test_obsolete_or_non_strict_metadata_rejected_without_writing(
    tmp_path, monkeypatch, field, value
):
    loader = _build_loader(tmp_path, monkeypatch)
    before = loader._plugins_index_file.read_bytes()
    with pytest.raises(ValidationError):
        PluginSettings.model_validate({field: value})
    assert loader.save({f"plugins.packages.demo.{field}": value}) is False
    assert loader._plugins_index_file.read_bytes() == before
    assert loader.load().plugins.packages == {}


@pytest.mark.parametrize(
    "payload", [[], None, {"packages": []}, {"unexpected": {}}, {"packages": {"../escape": {}}}]
)
def test_package_index_rejects_invalid_shape(tmp_path, monkeypatch, payload):
    loader = _build_loader(tmp_path, monkeypatch)
    loader._plugins_index_file.write_text(yaml.safe_dump(payload))
    before = loader._plugins_index_file.read_bytes()
    with pytest.raises(ValidationError):
        loader.reload()
    assert loader._plugins_index_file.read_bytes() == before


def test_legacy_chrome_and_inline_package_settings_are_not_migrated(tmp_path, monkeypatch):
    loader = _build_loader(tmp_path, monkeypatch)
    index = loader._plugins_index_file
    index.write_text("packages:\n  chrome-history:\n    enabled: false\n    trusted: false\n")
    settings = index.parent / "chrome-history.yaml"
    settings.write_text("sources: {chrome_history: {enabled: false}}\n")
    before = index.read_bytes(), settings.read_bytes()
    with pytest.raises(ValidationError):
        loader.reload()
    assert (index.read_bytes(), settings.read_bytes()) == before
    index.write_text("packages: {}\n")
    loader._config_file.write_text("plugins: {packages: {demo: {trusted: true}}}\n")
    agent_before = loader._config_file.read_bytes()
    with pytest.raises(ValueError, match="plugin index"):
        loader.reload()
    assert loader._config_file.read_bytes() == agent_before


def test_manifest_defaults_and_orphan_files_do_not_seed_settings(tmp_path, monkeypatch):
    loader = _build_loader(tmp_path, monkeypatch)
    manifest = tmp_path / "plugin.toml"
    manifest.write_text('[plugin.default_settings]\nsecret = "not-an-account"\n')
    orphan = loader._plugins_index_file.parent / "demo.yaml"
    orphan.write_text("enabled: true\nsecret: ignored\n")
    assert loader.save({"plugins.packages.demo.manifest_path": str(manifest)})
    cached = loader.load()
    assert cached.plugins.packages["demo"].trusted is False
    assert not hasattr(cached.plugins.packages["demo"], "settings")
    orphan.write_text("secret: still-ignored\n")
    assert loader.load() is cached
    assert (
        loader.reload().plugins.packages["demo"].model_dump()
        == PluginSettings(manifest_path=str(manifest)).model_dump()
    )
