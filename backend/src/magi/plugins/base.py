"""Unified plugin base classes."""
from __future__ import annotations

from abc import ABC
from pathlib import Path
from typing import Any, Optional

from .contracts import PluginManifest, PluginSettingsResourceSpec
from .i18n import PluginI18n, get_current_language


class Plugin(ABC):
    """Base class for multi-contribution plugin packages."""

    def __init__(self) -> None:
        self.manifest: PluginManifest | None = None
        self.settings: dict[str, Any] = {}
        self._i18n: PluginI18n | None = None

    @property
    def plugin_id(self) -> str:
        return self.manifest.plugin_id if self.manifest is not None else self.__class__.__name__

    @property
    def plugin_dir(self) -> Path | None:
        """Get the plugin directory path from manifest or class location."""
        if self.manifest and self.manifest.manifest_path:
            return Path(self.manifest.manifest_path).parent
        # Fallback: derive from class module location
        import inspect
        module = inspect.getmodule(self.__class__)
        if module and module.__file__:
            return Path(module.__file__).parent
        return None

    @property
    def i18n(self) -> PluginI18n:
        """Get the i18n helper for this plugin."""
        if self._i18n is None:
            plugin_dir = self.plugin_dir
            if plugin_dir is None:
                # Create a dummy i18n that returns keys as-is
                self._i18n = PluginI18n(self.plugin_id, Path("."))
            else:
                self._i18n = PluginI18n(self.plugin_id, plugin_dir)
        return self._i18n

    def configure(self, *, manifest: PluginManifest, settings: dict[str, Any]) -> None:
        """Bind manifest and persisted settings to the plugin instance."""

        self.manifest = manifest
        self.settings = dict(settings)
        # Reset i18n to pick up new plugin directory
        self._i18n = None

    def t(
        self,
        key: str,
        language: Optional[str] = None,
        fallback: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Get a translated string for this plugin.

        Args:
            key: Translation key (dot-notation)
            language: Target language (defaults to current thread language)
            fallback: Fallback string if translation not found
            **kwargs: Variables for string interpolation

        Returns:
            Translated and interpolated string
        """
        # Use provided language, or fall back to thread-local language
        effective_language = language or get_current_language()
        return self.i18n.t(key, language=effective_language, fallback=fallback, **kwargs)

    def get_tools(self) -> list[type[Any]]:
        return []

    def get_sensors(self) -> list[tuple[str, Any, Any]]:
        return []

    def get_channel(self) -> Any | None:
        """Return a configured Channel instance, or None if this plugin has no channel."""
        return None

    def get_channel_fields(self) -> list[Any]:
        """Return ExtensionFieldSpec list for the channel settings surface."""
        return []

    def get_plugin_ingress_registrations(self, *, runtime_paths: Any) -> list[Any]:
        return []

    def get_settings_resources(self) -> list[PluginSettingsResourceSpec]:
        return []

    def read_settings_resource(self, resource_name: str) -> Any:
        raise KeyError(resource_name)

    def build_temporal_summary_features(
        self,
        *,
        source_type: str,
        events: list[dict[str, Any]],
        summary_category: str,
        period_start: float,
        period_end: float,
    ) -> dict[str, Any] | None:
        """Return plugin-specific temporal summary features for a source window."""

        _ = source_type, events, summary_category, period_start, period_end
        return None
