"""Unified plugin base classes."""
from __future__ import annotations

from abc import ABC
from typing import Any

from .contracts import PluginManifest


class Plugin(ABC):
    """Base class for multi-contribution plugin packages."""

    def __init__(self) -> None:
        self.manifest: PluginManifest | None = None
        self.settings: dict[str, Any] = {}

    @property
    def plugin_id(self) -> str:
        return self.manifest.plugin_id if self.manifest is not None else self.__class__.__name__

    def configure(self, *, manifest: PluginManifest, settings: dict[str, Any]) -> None:
        """Bind manifest and persisted settings to the plugin instance."""

        self.manifest = manifest
        self.settings = dict(settings)

    def get_tools(self) -> list[type[Any]]:
        return []

    def get_sensors(self) -> list[tuple[str, Any, Any]]:
        return []

    def get_actions(self) -> list[Any]:
        return []
