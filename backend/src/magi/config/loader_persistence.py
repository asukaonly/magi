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
from ..utils.log_redaction import refresh_known_log_secrets

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ConfigSaveWorkspace:
    agent_yaml: Dict[str, Any]
    llm_defaults: Dict[str, Any]
    llm_effective: Dict[str, Any]
    lifecycle_payload: Dict[str, Any]
    plugins_index: Dict[str, Any]


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

    def _build_validation_payload(
        self,
        agent_yaml: Dict[str, Any],
        llm_effective: Dict[str, Any],
        lifecycle_payload: Dict[str, Any],
        plugins_index: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = deepcopy(agent_yaml)
        plugins_node = payload.setdefault("plugins", {})
        if not isinstance(plugins_node, dict):
            plugins_node = {}
            payload["plugins"] = plugins_node

        raw_packages = plugins_index.get("packages", {}) if isinstance(plugins_index, dict) else {}
        packages = deepcopy(raw_packages) if isinstance(raw_packages, dict) else {}

        if "packages" in plugins_node:
            raise ValueError("Package metadata must be stored in the plugin index")
        plugins_node["packages"] = packages

        payload["llm"] = deepcopy(llm_effective)
        payload["lifecycle"] = deepcopy(lifecycle_payload)
        return payload

    def _prepare_agent_yaml_for_save(self, agent_yaml: Dict[str, Any]) -> None:
        agent_yaml.pop("llm", None)
        agent_yaml.setdefault("plugins", {})
        if isinstance(agent_yaml.get("plugins"), dict):
            if "packages" in agent_yaml["plugins"]:
                raise ValueError("Package metadata must be stored in the plugin index")
        self._prune_deprecated_memory_settings(agent_yaml)

    def _prepare_save_workspace(self) -> _ConfigSaveWorkspace:
        agent_yaml = self._load_yaml_file(self._config_file)
        self._prepare_agent_yaml_for_save(agent_yaml)
        plugins_index = self._load_package_index()
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

        relative_path = ".".join(parts[2:])
        self._set_nested_yaml(workspace.plugins_index, f"packages.{relative_path}", value)

    def _validate_save_workspace(self, workspace: _ConfigSaveWorkspace) -> None:
        validation_payload = self._build_validation_payload(
            workspace.agent_yaml,
            workspace.llm_effective,
            workspace.lifecycle_payload,
            workspace.plugins_index,
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

    def delete_plugin_package(self, plugin_id: str) -> bool:
        """Delete installed metadata, preserving bundled host packages."""
        with self._persistence_lock:
            snapshot = None
            try:
                index = self._load_package_index()
                package = index["packages"].get(plugin_id)
                if package is None or package.get("source") == "builtin":
                    return False
                snapshot = self._snapshot_file(self._plugins_index_file)
                del index["packages"][plugin_id]
                self._write_yaml_file(self._plugins_index_file, index)
                self._config = None
                self._config_signature = None
                self.load()
                return True
            except Exception:
                if snapshot is not None:
                    self._restore_file(self._plugins_index_file, snapshot)
                self._config = None
                self._config_signature = None
                logger.error("Failed to delete plugin package metadata | plugin_id=%s", plugin_id)
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
        refresh_known_log_secrets(updates)
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
