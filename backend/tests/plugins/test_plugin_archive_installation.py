from __future__ import annotations

from pathlib import Path
import threading
import zipfile

import pytest

from magi.config.models import AppConfig, PluginSettings
from magi.plugins import installation as installation_module
from magi.plugins import manager as manager_module
from magi.plugins import package_files
from magi.plugins.contracts import PluginCapability
from magi.plugins.manager import PluginManager
from magi.plugins.sensors import SensorRegistry
from magi.tools.registry import ToolRegistry


def _write_archive(
    root: Path,
    *,
    plugin_id: str = "archive-policy-test",
    version: str = "1.0.0",
    marker: str = "original",
    depends_on: list[str] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    archive_path = root / f"{plugin_id}-{version}.zip"
    dependencies_line = (
        "\ndepends_on = [" + ", ".join(f'"{dependency_id}"' for dependency_id in depends_on) + "]"
        if depends_on
        else ""
    )
    manifest = f"""
[plugin]
id = "{plugin_id}"
name = "Archive Policy Test"
version = "{version}"
entry_module = "plugin"
entry_class = "ArchivePolicyPlugin"
contribution_types = ["tool"]
{dependencies_line}

[[plugin.permissions.capabilities]]
capability = "network"
scope = ["example.com"]
""".strip()
    plugin_source = f"""
from magi_plugin_sdk import Plugin


class ArchivePolicyPlugin(Plugin):
    marker = "{marker}"

    def get_tools(self):
        return []
""".strip()
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(f"{plugin_id}/plugin.toml", manifest)
        archive.writestr(f"{plugin_id}/plugin.py", plugin_source)
    return archive_path


def _patch_config(
    monkeypatch: pytest.MonkeyPatch,
    config: AppConfig,
    *,
    save_succeeds: bool = True,
) -> list[dict[str, object]]:
    saved: list[dict[str, object]] = []

    def save(updates: dict[str, object]) -> bool:
        saved.append(updates)
        if not save_succeeds:
            return False
        for path, value in updates.items():
            prefix = "plugins.packages."
            assert path.startswith(prefix)
            package_path = path[len(prefix) :]
            plugin_id, separator, field_name = package_path.partition(".")
            assert separator
            current = config.plugins.packages.get(plugin_id, PluginSettings())
            payload = current.model_dump(mode="json")
            payload[field_name] = value
            config.plugins.packages[plugin_id] = PluginSettings.model_validate(payload)
        return True

    def delete(plugin_id: str) -> bool:
        return config.plugins.packages.pop(plugin_id, None) is not None

    monkeypatch.setattr(manager_module, "get_config", lambda: config)
    monkeypatch.setattr(manager_module, "save_config", save)
    monkeypatch.setattr(installation_module, "get_config", lambda: config)
    monkeypatch.setattr(installation_module, "save_config", save)
    monkeypatch.setattr(installation_module, "delete_plugin_package", delete)
    return saved


def _manager(user_root: Path) -> PluginManager:
    return PluginManager(
        tool_registry=ToolRegistry(),
        sensor_registry=SensorRegistry(),
        search_paths=[user_root],
        request_sensor_schedule_refresh=lambda: None,
    )


def test_archive_install_commits_reviewed_state_as_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "plugins"
    archive_path = _write_archive(tmp_path / "archives")
    config = AppConfig()
    saved = _patch_config(monkeypatch, config)
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: user_root)
    manager = _manager(user_root)
    consent = [PluginCapability(capability="network", scope=["example.com"])]
    persist = installation_module.save_config
    staged_paths: list[Path] = []
    install_staged_dependencies = manager._install_staged_dependencies

    def record_staging_path(
        staged_dir: Path,
        *,
        progress_reporter,
        workflow_budget=None,
    ) -> None:
        staged_paths.append(staged_dir)
        assert staged_dir.parent == user_root.parent
        assert not staged_dir.is_relative_to(user_root)
        install_staged_dependencies(
            staged_dir,
            progress_reporter=progress_reporter,
            workflow_budget=workflow_budget,
        )

    def persist_before_publish(updates: dict[str, object]) -> bool:
        assert not (user_root / "archive-policy-test").exists()
        return persist(updates)

    monkeypatch.setattr(manager, "_install_staged_dependencies", record_staging_path)
    monkeypatch.setattr(installation_module, "save_config", persist_before_publish)

    state = manager.install_plugin_from_archive(
        archive_path,
        consented_capabilities=consent,
    )

    package_config = config.plugins.packages["archive-policy-test"]
    assert state.enabled is False
    assert state.trusted is False
    assert state.loaded is False
    assert package_config.enabled is False
    assert package_config.trusted is False
    assert package_config.official is False
    assert package_config.consented_capabilities == consent
    assert (user_root / "archive-policy-test" / "plugin.toml").is_file()
    assert len(staged_paths) == 1
    assert len(saved) == 1


def test_archive_install_does_not_inherit_orphaned_package_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "plugins"
    archive_path = _write_archive(tmp_path / "archives")
    config = AppConfig()
    config.plugins.packages["archive-policy-test"] = PluginSettings(
        enabled=True,
        trusted=True,
        official=True,
        consented_capabilities=[PluginCapability(capability="filesystem_read")],
        settings={"keep": "value"},
    )
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: user_root)
    manager = _manager(user_root)
    consent = [PluginCapability(capability="network", scope=["example.com"])]

    state = manager.install_plugin_from_archive(
        archive_path,
        consented_capabilities=consent,
    )

    package_config = config.plugins.packages["archive-policy-test"]
    assert state.enabled is False
    assert state.trusted is False
    assert state.loaded is False
    assert state.current_settings == {}
    assert package_config.enabled is False
    assert package_config.trusted is False
    assert package_config.official is False
    assert package_config.consented_capabilities == consent
    assert package_config.settings == {}


def test_archive_install_rolls_back_when_reviewed_state_cannot_be_saved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "plugins"
    archive_path = _write_archive(tmp_path / "archives")
    config = AppConfig()
    _patch_config(monkeypatch, config, save_succeeds=False)
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: user_root)
    manager = _manager(user_root)

    with pytest.raises(RuntimeError, match="Failed to persist plugin installation state"):
        manager.install_plugin_from_archive(
            archive_path,
            consented_capabilities=[PluginCapability(capability="network", scope=["example.com"])],
        )

    assert not (user_root / "archive-policy-test").exists()
    assert "archive-policy-test" not in config.plugins.packages
    assert manager.get_package("archive-policy-test") is None
    assert manager.get_loaded_plugin("archive-policy-test") is None


def test_archive_install_restores_config_when_post_publish_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "plugins"
    archive_path = _write_archive(tmp_path / "archives")
    config = AppConfig()
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: user_root)
    manager = _manager(user_root)
    real_scan = manager.scan
    validation_failed = False

    def fail_first_post_publish_scan(*, persist_discovery: bool = True):
        nonlocal validation_failed
        if (user_root / "archive-policy-test").exists() and not validation_failed:
            validation_failed = True
            raise RuntimeError("post-publish validation failed")
        return real_scan(persist_discovery=persist_discovery)

    monkeypatch.setattr(manager, "scan", fail_first_post_publish_scan)

    with pytest.raises(RuntimeError, match="post-publish validation failed"):
        manager.install_plugin_from_archive(
            archive_path,
            consented_capabilities=[PluginCapability(capability="network", scope=["example.com"])],
        )

    assert validation_failed is True
    assert not (user_root / "archive-policy-test").exists()
    assert "archive-policy-test" not in config.plugins.packages
    assert manager.get_package("archive-policy-test") is None


def test_archive_install_never_replaces_an_existing_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "plugins"
    first_archive = _write_archive(
        tmp_path / "first",
        version="1.0.0",
        marker="original",
    )
    replacement_archive = _write_archive(
        tmp_path / "replacement",
        version="2.0.0",
        marker="replacement",
    )
    config = AppConfig()
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: user_root)
    manager = _manager(user_root)
    consent = [PluginCapability(capability="network", scope=["example.com"])]
    manager.install_plugin_from_archive(
        first_archive,
        consented_capabilities=consent,
    )

    with pytest.raises(ValueError, match="Cannot replace an installed plugin"):
        manager.install_plugin_from_archive(
            replacement_archive,
            consented_capabilities=consent,
        )

    installed_manifest = user_root / "archive-policy-test" / "plugin.toml"
    installed_plugin = user_root / "archive-policy-test" / "plugin.py"
    assert 'version = "1.0.0"' in installed_manifest.read_text(encoding="utf-8")
    assert 'marker = "original"' in installed_plugin.read_text(encoding="utf-8")


def test_archive_install_rejects_host_reserved_package_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "plugins"
    archive_path = _write_archive(
        tmp_path / "archives",
        plugin_id="calendar",
    )
    config = AppConfig()
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: user_root)
    manager = _manager(user_root)

    with pytest.raises(ValueError, match="Cannot replace an installed plugin"):
        manager.install_plugin_from_archive(
            archive_path,
            consented_capabilities=[PluginCapability(capability="network", scope=["example.com"])],
        )

    assert not (user_root / "calendar").exists()


def test_archive_install_rejects_unbound_package_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "plugins"
    archive_path = _write_archive(
        tmp_path / "archives",
        plugin_id="dependent-archive",
        depends_on=["shared-library"],
    )
    config = AppConfig()
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: user_root)
    manager = _manager(user_root)

    with pytest.raises(ValueError, match="installed from the marketplace"):
        manager.install_plugin_from_archive(
            archive_path,
            consented_capabilities=[],
        )

    assert manager.get_package("dependent-archive") is None
    assert "dependent-archive" not in config.plugins.packages
    assert not (user_root / "dependent-archive").exists()


def test_archive_preparation_does_not_hold_the_lifecycle_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "plugins"
    archive_path = _write_archive(tmp_path / "archives")
    config = AppConfig()
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(package_files, "user_plugins_root", lambda: user_root)
    manager = _manager(user_root)
    preparation_started = threading.Event()
    release_preparation = threading.Event()
    rescan_finished = threading.Event()
    install_errors: list[BaseException] = []

    def block_preparation(
        _staged_dir: Path,
        *,
        progress_reporter,
        workflow_budget=None,
    ) -> None:
        _ = progress_reporter, workflow_budget
        preparation_started.set()
        if not release_preparation.wait(timeout=5):
            raise TimeoutError("Timed out waiting to release plugin preparation")

    def install() -> None:
        try:
            manager.install_plugin_from_archive(
                archive_path,
                consented_capabilities=[
                    PluginCapability(capability="network", scope=["example.com"])
                ],
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            install_errors.append(exc)

    monkeypatch.setattr(manager, "_install_staged_dependencies", block_preparation)
    install_thread = threading.Thread(target=install, daemon=True)
    install_thread.start()
    assert preparation_started.wait(timeout=5)

    rescan_thread = threading.Thread(
        target=lambda: (manager.rescan_runtime(), rescan_finished.set()),
        daemon=True,
    )
    rescan_thread.start()

    assert rescan_finished.wait(timeout=0.5)
    release_preparation.set()
    install_thread.join(timeout=5)
    rescan_thread.join(timeout=5)

    assert install_thread.is_alive() is False
    assert rescan_thread.is_alive() is False
    assert install_errors == []
    assert manager.get_package("archive-policy-test") is not None
