"""Strict package metadata index; account settings live in the connection store."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from pydantic import BaseModel, ConfigDict, Field
from magi_plugin_sdk.contracts import PluginIdentifier
from .plugin_models import PluginSettings


class _PackageIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    packages: dict[PluginIdentifier, PluginSettings] = Field(default_factory=dict)


class ConfigPluginLayoutMixin:
    """Read only installed package identity, trust and consent from the index."""

    _config_file: Path
    _plugins_index_file: Path

    def _load_package_index(self) -> dict[str, Any]:
        if not self._plugins_index_file.exists():
            return {"packages": {}}
        with self._plugins_index_file.open(encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
        return _PackageIndex.model_validate(payload).model_dump(mode="json")

    def _ensure_split_plugin_config_layout(self) -> None:
        """Create an empty metadata index without seeding packages or accounts."""
        self._plugins_index_file.parent.mkdir(parents=True, exist_ok=True)
        if not self._plugins_index_file.exists():
            self._write_yaml_file(self._plugins_index_file, {"packages": {}})

    def _merge_split_plugin_config(self, agent_data: dict[str, Any]) -> dict[str, Any]:
        """Compose metadata from its one supported location, without migration."""
        merged = deepcopy(agent_data)
        plugins = merged.setdefault("plugins", {})
        if not isinstance(plugins, dict):
            raise ValueError("Plugin configuration must be an object")
        if "packages" in plugins:
            raise ValueError("Package metadata must be stored in the plugin index")
        plugins["packages"] = self._load_package_index()["packages"]
        return merged


__all__ = ["ConfigPluginLayoutMixin"]
