"""Save/persistence helpers for ConfigLoader."""

from __future__ import annotations

import logging
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from .diff_utils import deep_merge_dict, extract_dict_overrides
from .models import AppConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ConfigSaveWorkspace:
    agent_yaml: Dict[str, Any]
    llm_defaults: Dict[str, Any]
    llm_effective: Dict[str, Any]
    lifecycle_payload: Dict[str, Any]
    plugins_index: Dict[str, Any]
    plugin_settings_updates: Dict[str, Dict[str, Any]]


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    exists: bool
    content: bytes


class ConfigLoaderPersistenceMixin:
    """Persist app, LLM, and plugin configuration updates."""

    _config_file: Path
    _llm_config_file: Path
    _lifecycle_config_file: Path
    _plugins_index_file: Path
    _config_signature: tuple[tuple[str, int, int], ...] | None

    def _apply_plugin_settings_updates_to_data(
        self,
        plugin_id: str,
        settings_data: Dict[str, Any],
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged_settings = deepcopy(settings_data)
        for relative_path, value in updates.items():
            if relative_path:
                self._set_nested_yaml(merged_settings, relative_path, value)
            elif isinstance(value, dict):
                merged_settings = dict(value)
            else:
                raise ValueError(f"Plugin settings root must be a dict for {plugin_id}")
        return merged_settings

    def _build_validation_payload(
        self,
        agent_yaml: Dict[str, Any],
        llm_effective: Dict[str, Any],
        lifecycle_payload: Dict[str, Any],
        plugins_index: Dict[str, Any],
        plugin_settings_updates: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        payload = deepcopy(agent_yaml)
        plugins_node = payload.setdefault("plugins", {})
        if not isinstance(plugins_node, dict):
            plugins_node = {}
            payload["plugins"] = plugins_node

        raw_packages = plugins_index.get("packages", {}) if isinstance(plugins_index, dict) else {}
        packages = deepcopy(raw_packages) if isinstance(raw_packages, dict) else {}

        for plugin_id, raw_package_entry in list(packages.items()):
            if not isinstance(raw_package_entry, dict):
                continue
            plugin_file = self._indexed_plugin_settings_file(plugin_id)
            if plugin_file is None:
                raise ValueError(f"Unsafe plugin settings path for {plugin_id}")
            package_entry = dict(packages.get(plugin_id, {}))
            settings_data = self._load_yaml_file(plugin_file) if plugin_file.is_file() else {}
            updates = plugin_settings_updates.get(plugin_id)
            package_entry["settings"] = (
                self._apply_plugin_settings_updates_to_data(plugin_id, settings_data, updates)
                if updates
                else settings_data
            )
            packages[plugin_id] = package_entry

        unknown_settings_updates = set(plugin_settings_updates).difference(packages)
        if unknown_settings_updates:
            unknown_list = ", ".join(sorted(unknown_settings_updates))
            raise ValueError(f"Cannot save settings for unindexed plugins: {unknown_list}")

        if packages:
            plugins_node["packages"] = packages

        payload["llm"] = deepcopy(llm_effective)
        payload["lifecycle"] = deepcopy(lifecycle_payload)
        return payload

    def _prepare_agent_yaml_for_save(self, agent_yaml: Dict[str, Any]) -> None:
        agent_yaml.pop("llm", None)
        agent_yaml.setdefault("plugins", {})
        if isinstance(agent_yaml.get("plugins"), dict):
            agent_yaml["plugins"].pop("packages", None)
        self._prune_deprecated_memory_settings(agent_yaml)

    def _prepare_save_workspace(self) -> _ConfigSaveWorkspace:
        agent_yaml = self._load_yaml_file(self._config_file)
        self._prepare_agent_yaml_for_save(agent_yaml)
        plugins_index = self._merge_plugin_index_defaults(
            self._load_yaml_file(self._plugins_index_file)
        )
        llm_defaults = self._build_llm_defaults()
        llm_overrides = self._load_yaml_file(self._llm_config_file)
        llm_effective = deep_merge_dict(llm_defaults, llm_overrides)
        lifecycle_yaml = self._load_yaml_file(self._lifecycle_config_file)
        lifecycle_payload = dict(lifecycle_yaml.get("lifecycle") or lifecycle_yaml)
        return _ConfigSaveWorkspace(
            agent_yaml=agent_yaml,
            llm_defaults=llm_defaults,
            llm_effective=llm_effective,
            lifecycle_payload=lifecycle_payload,
            plugins_index=plugins_index,
            plugin_settings_updates={},
        )

    def _apply_save_updates(
        self,
        workspace: _ConfigSaveWorkspace,
        updates: Dict[str, Any],
    ) -> None:
        for path, value in updates.items():
            self._apply_save_update(workspace, path, value)

    def _apply_save_update(
        self,
        workspace: _ConfigSaveWorkspace,
        path: str,
        value: Any,
    ) -> None:
        if path.startswith("llm."):
            self._set_nested_yaml(workspace.llm_effective, path[4:], value)
        elif path.startswith("lifecycle."):
            self._set_nested_yaml(workspace.lifecycle_payload, path[10:], value)
        elif path.startswith("plugins.packages."):
            self._apply_plugin_package_update(workspace, path, value)
        else:
            self._set_nested_yaml(workspace.agent_yaml, path, value)

    def _apply_plugin_package_update(
        self,
        workspace: _ConfigSaveWorkspace,
        path: str,
        value: Any,
    ) -> None:
        parts = path.split(".")
        if len(parts) < 4:
            self._set_nested_yaml(workspace.agent_yaml, path, value)
            return

        plugin_id = parts[2]
        if parts[3] == "settings":
            relative_path = ".".join(parts[4:])
            workspace.plugin_settings_updates.setdefault(plugin_id, {})[relative_path] = value
            return

        relative_path = ".".join(parts[2:])
        self._set_nested_yaml(workspace.plugins_index, f"packages.{relative_path}", value)

    def _validate_save_workspace(self, workspace: _ConfigSaveWorkspace) -> None:
        validation_payload = self._build_validation_payload(
            workspace.agent_yaml,
            workspace.llm_effective,
            workspace.lifecycle_payload,
            workspace.plugins_index,
            workspace.plugin_settings_updates,
        )
        AppConfig.model_validate(validation_payload)

    def _write_save_workspace(self, workspace: _ConfigSaveWorkspace) -> None:
        llm_overrides = extract_dict_overrides(workspace.llm_defaults, workspace.llm_effective)
        self._write_yaml_file(self._config_file, workspace.agent_yaml)
        self._write_yaml_file(self._llm_config_file, llm_overrides)
        self._write_yaml_file(
            self._lifecycle_config_file, {"lifecycle": workspace.lifecycle_payload}
        )
        self._write_yaml_file(self._plugins_index_file, workspace.plugins_index)
        self._write_plugin_settings_updates(workspace.plugin_settings_updates)

    def _write_plugin_settings_updates(
        self,
        plugin_settings_updates: Dict[str, Dict[str, Any]],
    ) -> None:
        for plugin_id, plugin_updates in plugin_settings_updates.items():
            plugin_file = self._indexed_plugin_settings_file(plugin_id)
            if plugin_file is None:
                raise ValueError(f"Unsafe plugin settings path for {plugin_id}")
            plugin_yaml = self._load_yaml_file(plugin_file)
            plugin_yaml = self._apply_plugin_settings_updates_to_data(
                plugin_id,
                plugin_yaml,
                plugin_updates,
            )
            self._write_yaml_file(plugin_file, plugin_yaml)

    @staticmethod
    def _snapshot_file(path: Path) -> _FileSnapshot:
        if not path.exists():
            return _FileSnapshot(exists=False, content=b"")
        return _FileSnapshot(exists=True, content=path.read_bytes())

    @staticmethod
    def _restore_file(path: Path, snapshot: _FileSnapshot) -> None:
        if not snapshot.exists:
            path.unlink(missing_ok=True)
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        rollback_path = path.with_name(f".{path.name}.{uuid4().hex}.rollback")
        try:
            with rollback_path.open("wb") as handle:
                handle.write(snapshot.content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(rollback_path, path)
        finally:
            rollback_path.unlink(missing_ok=True)

    @staticmethod
    def _remove_plugin_settings_file(path: Path) -> None:
        path.unlink(missing_ok=True)

    def _rollback_plugin_package_delete(
        self,
        *,
        index_snapshot: _FileSnapshot,
        settings_file: Path,
        settings_snapshot: _FileSnapshot,
    ) -> None:
        rollback_errors: list[str] = []
        for path, snapshot in (
            (self._plugins_index_file, index_snapshot),
            (settings_file, settings_snapshot),
        ):
            try:
                self._restore_file(path, snapshot)
            except OSError as exc:
                rollback_errors.append(f"{path}: {exc}")
        if rollback_errors:
            logger.critical(
                "Plugin package config rollback incomplete | errors=%s",
                rollback_errors,
            )

    def delete_plugin_package(self, plugin_id: str) -> bool:
        """Delete a user-installed package entry and its settings atomically."""
        with self._persistence_lock:
            return self._delete_plugin_package(plugin_id)

    def _delete_plugin_package(self, plugin_id: str) -> bool:
        """Delete a user-installed package entry and its settings atomically.

        Builtin package defaults cannot be removed through this operation.
        The index is updated first, so an unexpected process exit cannot let
        an orphaned settings file recreate the package.
        """
        index_snapshot: _FileSnapshot | None = None
        settings_snapshot: _FileSnapshot | None = None
        settings_file: Path | None = None

        try:
            index_data = self._load_yaml_file(self._plugins_index_file)
            packages = index_data.get("packages")
            if not isinstance(packages, dict) or plugin_id not in packages:
                logger.warning(
                    "Plugin package config not found | plugin_id=%s",
                    plugin_id,
                )
                return False

            package_entry = packages[plugin_id]
            builtin_packages = self._default_plugin_index_data().get("packages", {})
            if plugin_id in builtin_packages or (
                isinstance(package_entry, dict) and package_entry.get("source") == "builtin"
            ):
                logger.warning(
                    "Builtin plugin package config cannot be deleted | plugin_id=%s",
                    plugin_id,
                )
                return False

            settings_file = self._indexed_plugin_settings_file(plugin_id)
            if settings_file is None:
                return False

            index_snapshot = self._snapshot_file(self._plugins_index_file)
            settings_snapshot = self._snapshot_file(settings_file)

            updated_index = deepcopy(index_data)
            updated_packages = updated_index.get("packages")
            if not isinstance(updated_packages, dict):
                return False
            del updated_packages[plugin_id]

            self._write_yaml_file(self._plugins_index_file, updated_index)
            self._remove_plugin_settings_file(settings_file)

            self._config = None
            self._config_signature = None
            self.load()
            logger.info(
                "Plugin package config deleted | plugin_id=%s",
                plugin_id,
            )
            return True
        except Exception as exc:
            if (
                index_snapshot is not None
                and settings_snapshot is not None
                and settings_file is not None
            ):
                self._rollback_plugin_package_delete(
                    index_snapshot=index_snapshot,
                    settings_file=settings_file,
                    settings_snapshot=settings_snapshot,
                )
            self._config = None
            self._config_signature = None
            logger.error(
                "Failed to delete plugin package config | plugin_id=%s | error=%s",
                plugin_id,
                exc,
            )
            return False

    def save(self, updates: Dict[str, Any]) -> bool:
        """
        Save configuration updates.

        Args:
            updates: Dictionary of dot-separated paths to values

        Returns:
            True if saved successfully
        """
        with self._persistence_lock:
            return self._save(updates)

    def _save(self, updates: Dict[str, Any]) -> bool:
        """Persist configuration updates while holding the persistence lock."""
        try:
            update_keys = sorted(updates.keys())
            logger.info("Configuration save requested | update_paths=%s", update_keys)

            workspace = self._prepare_save_workspace()
            self._apply_save_updates(workspace, updates)
            self._validate_save_workspace(workspace)
            self._write_save_workspace(workspace)
            self._config = None
            self.load()

            logger.info(
                "Configuration saved | config_file=%s | update_paths=%s",
                str(self._config_file),
                update_keys,
            )
            return True

        except Exception as e:
            logger.error(
                "Failed to save config | update_paths=%s | error=%s",
                sorted(updates.keys()),
                str(e),
            )
            return False


__all__ = ["ConfigLoaderPersistenceMixin"]
