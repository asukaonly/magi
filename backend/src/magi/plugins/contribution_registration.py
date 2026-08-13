"""Registration of plugin contributions into host registries."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from .base import Plugin
from .contracts import ContributionType, PluginContribution, PluginManifest
from .history_importers import HistoryImporterRegistry
from .sensors import SensorRegistry
from .settings_service import (
    collect_plugin_settings_actions,
    settings_actions_for_contribution,
)

logger = logging.getLogger(__name__)


class PluginContributionRegistrar:
    """Register and unregister loaded plugin contributions."""

    def __init__(
        self,
        *,
        tool_registry: Any,
        sensor_registry: SensorRegistry,
        history_importer_registry: HistoryImporterRegistry | None = None,
        hook_registry_provider: Callable[[], Any | None] | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._sensor_registry = sensor_registry
        self._history_importer_registry = history_importer_registry or HistoryImporterRegistry()
        self._hook_registry_provider = hook_registry_provider or _resolve_hook_registry
        self._registered_tools: dict[str, list[str]] = {}
        self._registered_sensors: dict[str, list[str]] = {}
        self._registered_hooks: dict[str, list[tuple[Any, Any]]] = {}

    @property
    def history_importer_registry(self) -> HistoryImporterRegistry:
        return self._history_importer_registry

    def register(
        self,
        *,
        plugin_id: str,
        manifest: PluginManifest,
        plugin_instance: Plugin,
    ) -> list[PluginContribution]:
        """Register a loaded plugin's host-facing contributions."""

        settings_actions = collect_plugin_settings_actions(plugin_instance)
        registered_contributions: list[PluginContribution] = []

        self._register_tools(
            plugin_id=plugin_id,
            plugin_instance=plugin_instance,
            settings_actions=settings_actions,
            registered_contributions=registered_contributions,
        )
        self._register_sensors(
            plugin_id=plugin_id,
            manifest=manifest,
            plugin_instance=plugin_instance,
            settings_actions=settings_actions,
            registered_contributions=registered_contributions,
        )
        self._register_history_importers(
            plugin_id=plugin_id,
            plugin_instance=plugin_instance,
            registered_contributions=registered_contributions,
        )
        self._register_channel(
            plugin_id=plugin_id,
            manifest=manifest,
            plugin_instance=plugin_instance,
            settings_actions=settings_actions,
            registered_contributions=registered_contributions,
        )
        self._register_hooks(
            plugin_id=plugin_id,
            plugin_instance=plugin_instance,
            registered_contributions=registered_contributions,
        )
        return registered_contributions

    def unregister(self, plugin_id: str) -> None:
        """Unregister contributions previously registered for a plugin."""

        for tool_name in self._registered_tools.pop(plugin_id, []):
            self._tool_registry.unregister(tool_name)
        for sensor_id in self._registered_sensors.pop(plugin_id, []):
            self._sensor_registry.unregister(sensor_id)
        self._history_importer_registry.unregister_plugin(plugin_id)

        hook_entries = self._registered_hooks.pop(plugin_id, [])
        if not hook_entries:
            return
        registry = self._hook_registry_provider()
        if registry is None:
            return
        for event_type, handler in hook_entries:
            try:
                registry.unregister(event_type, handler)
            except Exception:
                logger.debug(
                    "Plugin hook unregister failed",
                    extra={"plugin_id": plugin_id, "event_type": str(event_type)},
                    exc_info=True,
                )

    def _register_tools(
        self,
        *,
        plugin_id: str,
        plugin_instance: Plugin,
        settings_actions: list[Any],
        registered_contributions: list[PluginContribution],
    ) -> None:
        tool_names: list[str] = []
        self._registered_tools[plugin_id] = tool_names
        for tool_class in plugin_instance.get_tools():
            tool_instance = tool_class()
            tool_schema = tool_instance.get_schema()
            tool_name = tool_schema.name
            setattr(tool_class, "_plugin_package_id", plugin_id)
            self._tool_registry.register(tool_class)
            tool_names.append(tool_name)
            tool_action_metadata = settings_actions_for_contribution(
                settings_actions,
                contribution_id=tool_name,
                contribution_type=ContributionType.TOOL,
                surface="tools",
            )
            registered_contributions.append(
                PluginContribution(
                    plugin_id=plugin_id,
                    contribution_id=tool_name,
                    contribution_type=ContributionType.TOOL,
                    display_name=tool_schema.name,
                    description=tool_schema.description,
                    surface="tools",
                    metadata={"settings_actions": tool_action_metadata}
                    if tool_action_metadata
                    else {},
                )
            )

    def _register_sensors(
        self,
        *,
        plugin_id: str,
        manifest: PluginManifest,
        plugin_instance: Plugin,
        settings_actions: list[Any],
        registered_contributions: list[PluginContribution],
    ) -> None:
        sensor_ids: list[str] = []
        self._registered_sensors[plugin_id] = sensor_ids
        for sensor_id, sensor, spec in plugin_instance.get_sensors():
            bind_plugin_context = getattr(sensor, "bind_plugin_context", None)
            if callable(bind_plugin_context):
                bind_plugin_context(plugin_id=plugin_id, plugin_dir=manifest.plugin_dir)
            self._sensor_registry.register(plugin_id, sensor_id, sensor, spec)
            sensor_ids.append(sensor_id)
            sensor_metadata = {"domain": spec.domain, **dict(spec.metadata)}
            sensor_surface = _normalized_sensor_surface(spec.surface)
            sensor_action_metadata = settings_actions_for_contribution(
                settings_actions,
                contribution_id=sensor_id,
                contribution_type=ContributionType.SENSOR,
                surface=sensor_surface,
            )
            if sensor_action_metadata:
                sensor_metadata["settings_actions"] = sensor_action_metadata
            registered_contributions.append(
                PluginContribution(
                    plugin_id=plugin_id,
                    contribution_id=sensor_id,
                    contribution_type=ContributionType.SENSOR,
                    display_name=spec.display_name,
                    description=spec.description,
                    surface=sensor_surface,
                    fields=list(spec.fields),
                    metadata=sensor_metadata,
                )
            )

    def _register_channel(
        self,
        *,
        plugin_id: str,
        manifest: PluginManifest,
        plugin_instance: Plugin,
        settings_actions: list[Any],
        registered_contributions: list[PluginContribution],
    ) -> None:
        channel = plugin_instance.get_channel()
        if channel is None:
            return
        channel_contribution_id = f"{plugin_id}:channel"
        channel_action_metadata = settings_actions_for_contribution(
            settings_actions,
            contribution_id=channel_contribution_id,
            contribution_type=ContributionType.CHANNEL,
            surface="extensions",
        )
        registered_contributions.append(
            PluginContribution(
                plugin_id=plugin_id,
                contribution_id=channel_contribution_id,
                contribution_type=ContributionType.CHANNEL,
                display_name=manifest.name,
                description=manifest.description,
                surface="extensions",
                fields=list(plugin_instance.get_channel_fields()),
                metadata={"settings_actions": channel_action_metadata}
                if channel_action_metadata
                else {},
            )
        )

    def _register_history_importers(
        self,
        *,
        plugin_id: str,
        plugin_instance: Plugin,
        registered_contributions: list[PluginContribution],
    ) -> None:
        for importer_id, importer, spec in plugin_instance.get_history_importers():
            self._history_importer_registry.register(
                plugin_id=plugin_id,
                importer_id=importer_id,
                importer=importer,
                spec=spec,
            )
            registered_contributions.append(
                PluginContribution(
                    plugin_id=plugin_id,
                    contribution_id=importer_id,
                    contribution_type=ContributionType.HISTORY_IMPORTER,
                    display_name=spec.display_name,
                    description=spec.description,
                    surface="extensions",
                    metadata={
                        "accepted_extensions": list(spec.accepted_extensions),
                        "format_version": spec.format_version,
                        "participant_identity_scope": spec.participant_identity_scope,
                        "export_help_url": spec.export_help_url,
                    },
                )
            )

    def _register_hooks(
        self,
        *,
        plugin_id: str,
        plugin_instance: Plugin,
        registered_contributions: list[PluginContribution],
    ) -> None:
        try:
            hook_specs = list(plugin_instance.get_hooks() or [])
        except AttributeError:
            hook_specs = []
        except Exception:
            hook_specs = []
        if hook_specs:
            self._register_plugin_hooks(plugin_id, hook_specs, registered_contributions)

    def _register_plugin_hooks(
        self,
        plugin_id: str,
        hook_specs: list[tuple[Any, ...]],
        registered_contributions: list[PluginContribution],
    ) -> None:
        registry = self._hook_registry_provider()
        if registry is None:
            return
        try:
            from ..hooks.contracts import HookEventType
        except Exception:
            return

        recorded: list[tuple[Any, Any]] = []
        for raw_index, spec in enumerate(hook_specs):
            parsed = _parse_hook_spec(spec, event_type_cls=HookEventType)
            if parsed is None:
                continue
            event_type, handler, matcher = parsed
            try:
                registry.register(
                    event_type,
                    handler,
                    matcher=str(matcher) if matcher else None,
                    source=f"plugin:{plugin_id}",
                )
            except TypeError:
                continue
            recorded.append((event_type, handler))
            registered_contributions.append(
                _build_hook_contribution(
                    plugin_id=plugin_id,
                    event_type=event_type,
                    matcher=matcher,
                    raw_index=raw_index,
                )
            )
        if recorded:
            self._registered_hooks[plugin_id] = recorded


def _normalized_sensor_surface(surface: str) -> str:
    return surface if surface in {"extensions", "tools", "timeline"} else "extensions"


def _parse_hook_spec(
    spec: Any,
    *,
    event_type_cls: Any,
) -> tuple[Any, Any, Any] | None:
    if not isinstance(spec, tuple) or len(spec) < 2:
        return None
    try:
        event_type = event_type_cls(spec[0])
    except ValueError:
        return None
    handler = spec[1]
    matcher = spec[2] if len(spec) >= 3 else None
    return event_type, handler, matcher


def _build_hook_contribution(
    *,
    plugin_id: str,
    event_type: Any,
    matcher: Any,
    raw_index: int,
) -> PluginContribution:
    return PluginContribution(
        plugin_id=plugin_id,
        contribution_id=f"{plugin_id}:hook:{event_type.value}:{raw_index}",
        contribution_type=ContributionType.HOOK,
        display_name=f"{event_type.value} hook",
        description=f"Hook contributed by {plugin_id}",
        surface="extensions",
        metadata={
            "event_type": event_type.value,
            "matcher": matcher,
        },
    )


def _resolve_hook_registry() -> Any | None:
    """Best-effort resolve of the shared HookRegistry."""
    try:
        from ..core.container import get_container

        registry = get_container().hook_registry()
    except Exception:
        return None
    if registry is None or type(registry).__name__ == "object":
        return None
    return registry
