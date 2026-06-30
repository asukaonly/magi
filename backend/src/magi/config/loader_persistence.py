"""Save/persistence helpers for ConfigLoader."""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

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

        seen_plugin_ids: set[str] = set(packages)
        for plugin_file in sorted(self._plugins_config_dir().glob("*.yaml")):
            if plugin_file.name == "index.yaml":
                continue
            plugin_id = plugin_file.stem
            seen_plugin_ids.add(plugin_id)
            package_entry = dict(packages.get(plugin_id, {}))
            settings_data = self._load_yaml_file(plugin_file)
            updates = plugin_settings_updates.get(plugin_id)
            package_entry["settings"] = (
                self._apply_plugin_settings_updates_to_data(plugin_id, settings_data, updates)
                if updates
                else settings_data
            )
            packages[plugin_id] = package_entry

        for plugin_id, updates in plugin_settings_updates.items():
            if plugin_id in seen_plugin_ids:
                continue
            package_entry = dict(packages.get(plugin_id, {}))
            package_entry["settings"] = self._apply_plugin_settings_updates_to_data(
                plugin_id, {}, updates
            )
            packages[plugin_id] = package_entry

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
            plugin_file = self._plugin_settings_file(plugin_id)
            plugin_yaml = self._load_yaml_file(plugin_file)
            plugin_yaml = self._apply_plugin_settings_updates_to_data(
                plugin_id,
                plugin_yaml,
                plugin_updates,
            )
            self._write_yaml_file(plugin_file, plugin_yaml)

    def save(self, updates: Dict[str, Any]) -> bool:
        """
        Save configuration updates.

        Args:
            updates: Dictionary of dot-separated paths to values

        Returns:
            True if saved successfully
        """
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
