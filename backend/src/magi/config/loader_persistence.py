"""Save/persistence helpers for ConfigLoader."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from .diff_utils import deep_merge_dict, extract_dict_overrides

logger = logging.getLogger(__name__)


def _loader_facade() -> Any:
    from . import loader

    return loader


class ConfigLoaderPersistenceMixin:
    """Persist app, LLM, and plugin configuration updates."""

    _config_file: Path
    _llm_config_file: Path
    _lifecycle_config_file: Path
    _plugins_index_file: Path
    _config_signature: tuple[tuple[str, int, int], ...] | None

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

            agent_yaml = self._load_yaml_file(self._config_file)
            if "llm" in agent_yaml:
                del agent_yaml["llm"]
            agent_yaml.setdefault("plugins", {})
            if isinstance(agent_yaml.get("plugins"), dict) and "packages" in agent_yaml["plugins"]:
                del agent_yaml["plugins"]["packages"]
            self._prune_deprecated_memory_settings(agent_yaml)
            plugins_index = self._merge_plugin_index_defaults(self._load_yaml_file(self._plugins_index_file))
            llm_defaults = self._build_llm_defaults()
            llm_overrides = self._load_yaml_file(self._llm_config_file)
            llm_effective = deep_merge_dict(llm_defaults, llm_overrides)
            lifecycle_yaml = self._load_yaml_file(self._lifecycle_config_file)
            lifecycle_payload = dict(lifecycle_yaml.get("lifecycle") or lifecycle_yaml)
            plugin_settings_updates: Dict[str, Dict[str, Any]] = {}

            for path, value in updates.items():
                if path.startswith("llm."):
                    self._set_nested_yaml(llm_effective, path[4:], value)
                    continue

                if path.startswith("lifecycle."):
                    self._set_nested_yaml(lifecycle_payload, path[10:], value)
                    continue

                if path.startswith("plugins.packages."):
                    parts = path.split(".")
                    if len(parts) < 4:
                        self._set_nested_yaml(agent_yaml, path, value)
                        continue
                    plugin_id = parts[2]
                    if parts[3] == "settings":
                        relative_path = ".".join(parts[4:])
                        plugin_settings_updates.setdefault(plugin_id, {})[relative_path] = value
                    else:
                        relative_path = ".".join(parts[2:])
                        self._set_nested_yaml(plugins_index, f"packages.{relative_path}", value)
                    continue

                self._set_nested_yaml(agent_yaml, path, value)

            llm_overrides = extract_dict_overrides(llm_defaults, llm_effective)

            self._write_yaml_file(self._config_file, agent_yaml)
            self._write_yaml_file(self._llm_config_file, llm_overrides)
            self._write_yaml_file(self._lifecycle_config_file, {"lifecycle": lifecycle_payload})
            self._write_yaml_file(self._plugins_index_file, plugins_index)

            facade = _loader_facade()
            for plugin_id, plugin_updates in plugin_settings_updates.items():
                plugin_yaml = self._load_yaml_file(facade.get_plugin_settings_file(plugin_id))
                for relative_path, value in plugin_updates.items():
                    if relative_path:
                        self._set_nested_yaml(plugin_yaml, relative_path, value)
                    elif isinstance(value, dict):
                        plugin_yaml = dict(value)
                    else:
                        raise ValueError(f"Plugin settings root must be a dict for {plugin_id}")
                self._write_yaml_file(facade.get_plugin_settings_file(plugin_id), plugin_yaml)

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
