"""Review permissions without freezing local source or enabling accounts."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from magi.config.models import AppConfig, PluginSettings
from magi.plugins import installation, manager as manager_module, package_files, package_integrity
from magi.plugins.connections import PluginConnectionStore
from magi.plugins.manager import PluginManager
from magi.plugins.operation_authorization import InstalledOperationAuthorizer
from magi.plugins.package_identity import compute_installed_package_sha256, compute_package_sha256
from magi.plugins.sources import SourceRegistry
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
        source_registry=SourceRegistry(),
        search_paths=[root],
        request_source_schedule_refresh=lambda: None,
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


def _reviewed_permissions(runtime):
    manifest = runtime.manager.get_package("reviewed").manifest
    return {
        "expected_capabilities": deepcopy(manifest.capabilities),
        "expected_execution_mode": manifest.execution_mode,
    }


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


def test_permission_approval_records_manifest_consent_without_runtime_side_effects(runtime):
    connection = runtime.store.create("reviewed", display_name="Account")
    digest = runtime.config.plugins.packages["reviewed"].package_sha256
    state = runtime.manager.authorize_package("reviewed", digest, **_reviewed_permissions(runtime))
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


@pytest.mark.parametrize("mutation", ["digest", "manifest", "missing_seal"])
def test_stale_installation_or_manifest_review_cannot_be_trusted(runtime, mutation):
    package = runtime.config.plugins.packages["reviewed"]
    digest = package.package_sha256
    root = Path(runtime.state.manifest.plugin_dir)
    if mutation == "digest":
        digest = "0" * 64
    elif mutation == "manifest":
        path = root / "plugin.toml"
        path.write_text(path.read_text().replace("example.com", "changed.example"))
    else:
        package.installed_package_sha256 = None
    before = len(runtime.saved)
    with pytest.raises(ValueError):
        runtime.manager.authorize_package("reviewed", digest, **_reviewed_permissions(runtime))
    assert len(runtime.saved) == before
    assert runtime.config.plugins.packages["reviewed"].trusted is False
    assert runtime.state.trusted is False
    runtime.factory.assert_not_called()


@pytest.mark.parametrize("install_origin", ["local", "upload", "registry"])
def test_local_edits_preserve_consent_without_reading_package_contents(
    runtime, monkeypatch, install_origin
):
    package = runtime.config.plugins.packages["reviewed"]
    package.install_origin = install_origin
    if install_origin == "registry":
        package.registry_source = "https://example.test/registry.json"
        package.registry_repo_url = "https://example.test/plugins.git"
    root = Path(runtime.state.manifest.plugin_dir)
    (root / "plugin.py").write_text("changed_before_approval = True\n")
    digest = package.package_sha256
    seal = package.installed_package_sha256
    forbidden = Mock(side_effect=AssertionError("Runtime must not hash or purge package files"))
    for name in (
        "verify_installed_source_sha256",
        "verify_installed_package_sha256",
        "purge_plugin_bytecode_caches",
    ):
        monkeypatch.setattr(package_integrity, name, forbidden)
    runtime.manager.scan()
    runtime.manager.authorize_package("reviewed", digest, **_reviewed_permissions(runtime))
    (root / "plugin.py").write_text("changed_after_approval = True\n")
    dependencies = root / ".deps"
    dependencies.mkdir()
    (dependencies / "custom.py").write_text("edited_dependency = True\n")
    runtime.manager.scan()
    state = runtime.manager.get_package("reviewed")
    assert state.trusted and state.healthy
    assert state.last_error is None
    connection = runtime.store.create("reviewed", display_name="Account")
    runtime.manager._authorize_connection(connection)
    current = runtime.config.plugins.packages["reviewed"]
    assert current.package_sha256 == digest
    assert current.installed_package_sha256 == seal
    forbidden.assert_not_called()
    runtime.factory.assert_not_called()


def test_manifest_edits_do_not_grant_new_capability_scopes(runtime):
    path = Path(runtime.state.manifest.manifest_path)
    path.write_text(path.read_text() + (
        '\n[[plugin.settings_resources]]\nresource_name = "login"\nrequires_enabled = false\n'
    ))
    runtime.manager.scan()
    package = runtime.config.plugins.packages["reviewed"]
    runtime.manager.authorize_package(
        "reviewed", package.package_sha256, **_reviewed_permissions(runtime)
    )
    connection = runtime.store.create("reviewed", display_name="Account")
    authorizer = InstalledOperationAuthorizer(
        get_package=runtime.manager.get_package,
        connection_store=runtime.store,
        config_provider=lambda: runtime.config,
    )
    assert authorizer.authorize_setup_connection(connection)
    path.write_text(path.read_text().replace("example.com", "changed.example"))
    runtime.manager.scan()
    assert runtime.manager.get_package("reviewed").trusted
    assert not authorizer.authorize_setup_connection(connection)
    runtime.manager.authorize_package(
        "reviewed", package.package_sha256, **_reviewed_permissions(runtime)
    )
    assert authorizer.authorize_setup_connection(connection)
    runtime.factory.assert_not_called()


@pytest.mark.parametrize("change", ["capabilities", "execution_mode"])
def test_rescan_cannot_authorize_permissions_from_a_stale_dialog(runtime, change):
    review = _reviewed_permissions(runtime)
    digest = runtime.config.plugins.packages["reviewed"].package_sha256
    path = Path(runtime.state.manifest.manifest_path)
    original, replacement = (
        ("example.com", "changed.example")
        if change == "capabilities"
        else ("trusted_process", "restricted_process")
    )
    path.write_text(path.read_text().replace(original, replacement))
    runtime.manager.scan()
    with pytest.raises(ValueError, match="permissions changed"):
        runtime.manager.authorize_package("reviewed", digest, **review)
    assert not runtime.manager.get_package("reviewed").trusted
    assert not runtime.config.plugins.packages["reviewed"].trusted
    runtime.factory.assert_not_called()


def test_authorization_persistence_failure_never_changes_runtime_trust(runtime, monkeypatch):
    monkeypatch.setattr(manager_module, "save_config", lambda updates: False)
    digest = runtime.config.plugins.packages["reviewed"].package_sha256
    with pytest.raises(RuntimeError, match="persist"):
        runtime.manager.authorize_package("reviewed", digest, **_reviewed_permissions(runtime))
    assert runtime.state.trusted is False
    assert runtime.config.plugins.packages["reviewed"].trusted is False
    runtime.factory.assert_not_called()
