"""A reviewed artifact can be trusted without loading code or enabling accounts."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from magi.config.models import AppConfig, PluginSettings
from magi.plugins import installation, manager as manager_module, package_files
from magi.plugins.connections import PluginConnectionStore
from magi.plugins.manager import PluginManager
from magi.plugins.package_identity import compute_installed_package_sha256, compute_package_sha256
from magi.plugins.sensors import SensorRegistry
from magi.tools.registry import ToolRegistry
from magi.utils.runtime import RuntimePaths

MANIFEST = """[plugin]
id = "reviewed"
name = "Reviewed package"
version = "1.0.0"
protocol_version = 2
min_sdk_version = "0.2.0"
execution_mode = "trusted_process"
entry_module = "plugin"
entry_class = "ReviewPlugin"
[[plugin.permissions.capabilities]]
capability = "network"
scope = ["example.com"]
"""


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    root.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    (source / "plugin.toml").write_text(MANIFEST)
    (source / "plugin.py").write_text('raise AssertionError("Package must not be imported")\n')
    config = AppConfig()
    saved = []

    def save(updates):
        payload = deepcopy(config.plugins.packages)
        for path, value in updates.items():
            plugin_id, field = path.removeprefix("plugins.packages.").split(".", 1)
            raw = payload.get(plugin_id, PluginSettings()).model_dump(mode="json")
            raw[field] = value
            payload[plugin_id] = PluginSettings.model_validate(raw)
        config.plugins.packages = payload
        saved.append(updates)
        return True

    monkeypatch.setattr(manager_module, "get_config", lambda: config)
    monkeypatch.setattr(manager_module, "save_config", save)
    monkeypatch.setattr(installation, "get_config", lambda: config)
    monkeypatch.setattr(installation, "save_config", save)
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: root)
    store = PluginConnectionStore(
        runtime_paths=RuntimePaths(base_dir=tmp_path / "runtime"),
        require_package=lambda plugin_id: manager._require_connection_package(plugin_id),
        authorize_enable=lambda connection: manager._authorize_connection(connection),
    )
    factory = Mock(side_effect=AssertionError("Authorization must not create workers"))
    manager = PluginManager(
        tool_registry=ToolRegistry(),
        sensor_registry=SensorRegistry(),
        search_paths=[root],
        request_sensor_schedule_refresh=lambda: None,
        connection_store=store,
        instance_factory=factory,
    )
    state = manager.install_plugin_from_directory(source)
    return SimpleNamespace(
        manager=manager,
        store=store,
        source=source,
        state=state,
        config=config,
        saved=saved,
        factory=factory,
    )


def test_local_install_is_sealed_untrusted_and_has_no_default_connection(runtime):
    package = runtime.config.plugins.packages["reviewed"]
    assert package.trusted is False
    assert package.package_sha256 == compute_package_sha256(runtime.source)
    assert package.installed_package_sha256 == compute_installed_package_sha256(
        Path(runtime.state.manifest.plugin_dir)
    )
    assert runtime.store.list("reviewed") == []
    assert runtime.state.enabled is False
    assert runtime.state.loaded is False
    runtime.factory.assert_not_called()


def test_exact_artifact_approval_records_manifest_consent_without_runtime_side_effects(runtime):
    connection = runtime.store.create("reviewed", display_name="Account")
    digest = runtime.config.plugins.packages["reviewed"].package_sha256
    state = runtime.manager.authorize_package("reviewed", digest)
    package = runtime.config.plugins.packages["reviewed"]
    assert package.trusted and state.trusted
    assert package.consented_capabilities == state.manifest.capabilities
    assert runtime.store.get(connection.connection_id) == connection
    assert state.loaded is False and state.enabled is False
    runtime.factory.assert_not_called()
    assert set(runtime.saved[-1]) == {
        "plugins.packages.reviewed.trusted",
        "plugins.packages.reviewed.consented_capabilities",
    }


@pytest.mark.parametrize("mutation", ["digest", "source", "seal", "manifest", "missing_seal"])
def test_stale_or_changed_artifact_cannot_be_trusted(runtime, mutation):
    package = runtime.config.plugins.packages["reviewed"]
    digest = package.package_sha256
    root = Path(runtime.state.manifest.plugin_dir)
    if mutation == "digest":
        digest = "0" * 64
    elif mutation == "source":
        (root / "plugin.py").write_text("changed = True\n")
    elif mutation == "seal":
        package.installed_package_sha256 = "0" * 64
    elif mutation == "manifest":
        path = root / "plugin.toml"
        path.write_text(path.read_text().replace("example.com", "changed.example"))
    else:
        package.installed_package_sha256 = None
    before = len(runtime.saved)
    with pytest.raises(ValueError):
        runtime.manager.authorize_package("reviewed", digest)
    assert len(runtime.saved) == before
    assert runtime.config.plugins.packages["reviewed"].trusted is False
    assert runtime.state.trusted is False
    runtime.factory.assert_not_called()


def test_authorization_persistence_failure_never_changes_runtime_trust(runtime, monkeypatch):
    monkeypatch.setattr(manager_module, "save_config", lambda updates: False)
    digest = runtime.config.plugins.packages["reviewed"].package_sha256
    with pytest.raises(RuntimeError, match="persist"):
        runtime.manager.authorize_package("reviewed", digest)
    assert runtime.state.trusted is False
    assert runtime.config.plugins.packages["reviewed"].trusted is False
    runtime.factory.assert_not_called()
