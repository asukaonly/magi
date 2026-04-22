"""Unified plugin base class."""
from __future__ import annotations

from abc import ABC
from pathlib import Path
from typing import Any, Optional

from .channels import Channel
from .contracts import ExtensionFieldSpec, PluginManifest, PluginSettingsResourceSpec
from .ingress import PluginIngressHandlerRegistration
from .i18n import PluginI18n, get_current_language
from .sensors import PluginRuntimePaths, SensorSpec


class Plugin(ABC):
    """Base class for Magi plugin packages.

    Subclass this and implement one or more capability hooks to contribute
    tools, sensors, channels, settings resources, ingress handlers, or
    temporal summary features to the Magi runtime.

    The runtime calls ``configure()`` before registration, so ``self.manifest``
    and ``self.settings`` are available inside all plugin methods.
    """

    def __init__(self) -> None:
        self.manifest: PluginManifest | None = None
        self.settings: dict[str, Any] = {}
        self._i18n: PluginI18n | None = None

    @property
    def plugin_id(self) -> str:
        """Return the plugin identifier from the manifest, or the class name."""
        return self.manifest.plugin_id if self.manifest is not None else self.__class__.__name__

    @property
    def plugin_dir(self) -> Path | None:
        """Resolve the plugin directory from the manifest or class file location."""
        if self.manifest and self.manifest.manifest_path:
            return Path(self.manifest.manifest_path).parent
        import inspect

        module = inspect.getmodule(self.__class__)
        if module and module.__file__:
            return Path(module.__file__).parent
        return None

    @property
    def i18n(self) -> PluginI18n:
        """Return the i18n helper for this plugin."""
        if self._i18n is None:
            plugin_dir = self.plugin_dir
            if plugin_dir is None:
                self._i18n = PluginI18n(self.plugin_id, Path("."))
            else:
                self._i18n = PluginI18n(self.plugin_id, plugin_dir)
        return self._i18n

    def configure(self, *, manifest: PluginManifest, settings: dict[str, Any]) -> None:
        """Bind manifest and persisted settings to the plugin instance."""
        self.manifest = manifest
        self.settings = dict(settings)
        self._i18n = None

    def t(
        self,
        key: str,
        language: Optional[str] = None,
        fallback: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Look up a translated string for this plugin.

        Args:
            key: Translation key in dot-notation (e.g. ``"summary.played_track"``).
            language: Target language code; defaults to the current context language.
            fallback: String to return when the key is not found.
            **kwargs: Variables substituted into the translated string.

        Returns:
            Translated and interpolated string, or *key* if no translation found.
        """
        effective_language = language or get_current_language()
        return self.i18n.t(key, language=effective_language, fallback=fallback, **kwargs)

    def get_tools(self) -> list[type[Any]]:
        """Return tool classes contributed by this plugin."""
        return []

    def get_sensors(self) -> list[tuple[str, Any, SensorSpec]]:
        """Return ``(sensor_id, sensor_instance, SensorSpec)`` tuples."""
        return []

    def get_channel(self) -> Channel | None:
        """Return an optional channel adapter instance contributed by this plugin."""
        return None

    def get_channel_fields(self) -> list[ExtensionFieldSpec]:
        """Return declarative settings fields for the optional channel contribution."""
        return []

    def get_settings_resources(self) -> list[PluginSettingsResourceSpec]:
        """Return read-only resource descriptors consumed by dynamic settings UI."""
        return []

    def read_settings_resource(self, resource_name: str) -> Any:
        """Resolve a named settings resource.

        Plugins that do not expose settings resources should keep the default
        implementation, which raises ``KeyError``.
        """
        raise KeyError(resource_name)

    def build_temporal_summary_features(
        self,
        *,
        source_type: str,
        events: list[dict[str, Any]],
        summary_category: str,
        period_start: float,
        period_end: float,
    ) -> dict[str, object] | None:
        """Return optional source-specific features for L3 temporal summaries."""
        _ = source_type, events, summary_category, period_start, period_end
        return None

    def get_plugin_ingress_registrations(
        self,
        *,
        runtime_paths: PluginRuntimePaths,
    ) -> list[PluginIngressHandlerRegistration]:
        """Return static ingress registrations for host-produced events."""
        _ = runtime_paths
        return []
