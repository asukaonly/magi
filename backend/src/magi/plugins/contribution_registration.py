"""Transactional registration of connection-owned plugin contributions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
import threading
from typing import Any

from .base import Plugin
from .contracts import ContributionType, PluginContribution, PluginManifest
from .history_importers import HistoryImporterRegistry
from .sensors import SensorRegistry
from .settings_service import collect_plugin_settings_actions, settings_actions_for_contribution


class PluginContributionRegistrar:
    """Publish a complete declaration or roll back only that registration's entries."""

    def __init__(
        self,
        *,
        tool_registry: Any,
        sensor_registry: SensorRegistry,
        history_importer_registry: HistoryImporterRegistry | None = None,
        hook_registry_provider: Callable[[], Any | None] | None = None,
        skill_registrar: Any | None = None,
        operation_registrar: Any | None = None,
        provider_registrar: Any | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._sensor_registry = sensor_registry
        self._history_importer_registry = history_importer_registry or HistoryImporterRegistry()
        self._hook_registry_provider = hook_registry_provider or _resolve_hook_registry
        self._skill_registrar = skill_registrar
        self._operation_registrar = operation_registrar
        self._provider_registrar = provider_registrar
        self._registrations: dict[str, list[Callable[[], None]]] = {}
        self._lock = threading.RLock()

    @property
    def history_importer_registry(self) -> HistoryImporterRegistry:
        return self._history_importer_registry

    def register(
        self,
        *,
        plugin_id: str,
        connection_id: str,
        manifest: PluginManifest,
        plugin_instance: Plugin,
    ) -> list[PluginContribution]:
        """Validate actual contribution kinds before publishing any host entries."""
        with self._lock:
            if manifest.plugin_id != plugin_id or plugin_instance.plugin_id != plugin_id:
                raise ValueError("Plugin registration identity does not match its manifest")
            if plugin_instance.connection_id != connection_id:
                raise ValueError("Plugin registration identity does not match its connection")
            if connection_id in self._registrations:
                raise ValueError(f"Connection contributions already registered: {connection_id}")
            tools = list(plugin_instance.get_tools())
            sensors = list(plugin_instance.get_sensors())
            importers = list(plugin_instance.get_history_importers())
            channel = plugin_instance.get_channel()
            hooks = list(plugin_instance.get_hooks())
            skills = list(plugin_instance.get_skills())
            operations = list(plugin_instance.get_operations())
            providers = list(plugin_instance.get_providers())
            actual = {
                kind
                for kind, values in (
                    (ContributionType.TOOL, tools),
                    (ContributionType.OPERATION, operations),
                    (ContributionType.PROVIDER, providers),
                    (ContributionType.SENSOR, sensors),
                    (ContributionType.HISTORY_IMPORTER, importers),
                    (ContributionType.CHANNEL, channel is not None),
                    (ContributionType.HOOK, hooks),
                    (ContributionType.SKILL, skills),
                )
                if values
            }
            declared = set(manifest.contribution_types)
            if declared != actual:
                missing = sorted(item.value for item in declared - actual)
                undeclared = sorted(item.value for item in actual - declared)
                raise ValueError(
                    f"Plugin contribution declaration mismatch: missing={missing}, "
                    f"undeclared={undeclared}"
                )
            settings_actions = collect_plugin_settings_actions(plugin_instance)
            contributions: list[PluginContribution] = []
            disposers: list[Callable[[], None]] = []
            seen: set[tuple[ContributionType, str]] = set()

            def host_id(local_id: str) -> str:
                if not local_id:
                    raise ValueError("Contribution id must not be empty")
                return local_id if manifest.source == "builtin" else f"{connection_id}:{local_id}"

            def record(kind: ContributionType, local_id: str, **kwargs: Any) -> None:
                key = (kind, local_id)
                if key in seen:
                    raise ValueError(f"Duplicate contribution: {kind.value}/{local_id}")
                seen.add(key)
                metadata = dict(kwargs.pop("metadata", {}))
                metadata.update(connection_id=connection_id, local_id=local_id)
                actions = settings_actions_for_contribution(
                    settings_actions,
                    contribution_id=local_id,
                    contribution_type=kind,
                    surface=kwargs.get("surface", "extensions"),
                )
                if actions:
                    metadata["settings_actions"] = actions
                contributions.append(
                    PluginContribution(
                        plugin_id=plugin_id,
                        contribution_id=host_id(local_id),
                        contribution_type=kind,
                        metadata=metadata,
                        **kwargs,
                    )
                )

            self._registrations[connection_id] = disposers
            try:
                for tool_class in tools:
                    tool = tool_class()
                    schema = tool.get_schema()
                    record(
                        ContributionType.TOOL,
                        schema.name,
                        display_name=schema.name,
                        description=schema.description,
                        surface="tools",
                    )
                    if self._operation_registrar is None:
                        raise RuntimeError("Plugin operation registry is unavailable")
                    if self._provider_registrar is not None:
                        disposers.append(self._provider_registrar.bind_tool(tool))
                    disposers.append(
                        self._operation_registrar.register_tool(
                            plugin_id=plugin_id,
                            connection_id=connection_id,
                            tool_class=tool_class,
                            tool_instance=tool,
                            registered_name=host_id(schema.name),
                        )
                    )
                for operation in operations:
                    record(
                        ContributionType.OPERATION,
                        operation.operation_id,
                        display_name=operation.operation_id,
                        description=operation.description,
                        surface="tools",
                    )
                    if self._operation_registrar is None:
                        raise RuntimeError("Plugin operation registry is unavailable")

                    async def invoke(arguments: Any, context: Any, _spec: Any = operation) -> Any:
                        return await plugin_instance.invoke_operation(
                            _spec.operation_id,
                            arguments,
                            context.invocation,
                        )

                    disposers.append(
                        self._operation_registrar.register(
                            plugin_id=plugin_id,
                            connection_id=connection_id,
                            spec=operation,
                            handler=invoke,
                            registered_name=host_id(operation.operation_id),
                        )
                    )
                for kind, provider_id, implementation in providers:
                    record(
                        ContributionType.PROVIDER,
                        provider_id,
                        display_name=provider_id,
                        description="",
                        surface="extensions",
                        metadata={"kind": kind},
                    )
                    if self._provider_registrar is None:
                        raise RuntimeError("Plugin provider registry is unavailable")
                    disposers.append(
                        self._provider_registrar.register(
                            plugin_id=plugin_id,
                            connection_id=connection_id,
                            kind=kind,
                            provider_id=host_id(provider_id),
                            implementation=implementation,
                        )
                    )
                for sensor_id, sensor, spec in sensors:
                    if sensor_id != spec.sensor_id:
                        raise ValueError("Sensor tuple id must match its spec")
                    surface = (
                        spec.surface
                        if spec.surface in {"extensions", "tools", "timeline"}
                        else "extensions"
                    )
                    record(
                        ContributionType.SENSOR,
                        sensor_id,
                        display_name=spec.display_name,
                        description=spec.description,
                        surface=surface,
                        fields=list(spec.fields),
                        metadata={"domain": spec.domain, **dict(spec.metadata)},
                    )
                    bind = getattr(sensor, "bind_plugin_context", None)
                    if callable(bind):
                        bind(
                            plugin_id=plugin_id,
                            plugin_dir=manifest.plugin_dir,
                            connection=plugin_instance.connection,
                            context=plugin_instance.context,
                        )
                    registered_id = host_id(sensor_id)
                    disposers.append(
                        self._sensor_registry.register(
                            plugin_id,
                            registered_id,
                            sensor,
                            replace(
                                spec,
                                sensor_id=registered_id,
                                metadata={
                                    **spec.metadata,
                                    "connection_id": connection_id,
                                    "local_sensor_id": sensor_id,
                                },
                            ),
                        )
                    )
                for importer_id, importer, spec in importers:
                    if importer_id != spec.importer_id:
                        raise ValueError("History importer tuple id must match its spec")
                    record(
                        ContributionType.HISTORY_IMPORTER,
                        importer_id,
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
                    disposers.append(
                        self._history_importer_registry.register(
                            plugin_id=plugin_id,
                            importer_id=importer_id,
                            importer=importer,
                            spec=spec,
                            connection_id=connection_id,
                        )
                    )
                if channel is not None:
                    record(
                        ContributionType.CHANNEL,
                        f"{plugin_id}:channel",
                        display_name=manifest.name,
                        description=manifest.description,
                        surface="extensions",
                        fields=list(plugin_instance.get_channel_fields()),
                    )
                for skill_id, path in skills:
                    if self._skill_registrar is None:
                        raise RuntimeError("Plugin skill registry is unavailable")
                    record(
                        ContributionType.SKILL,
                        skill_id,
                        display_name=skill_id,
                        description="",
                        surface="tools",
                    )
                    disposers.append(
                        self._skill_registrar.register(
                            plugin_id,
                            skill_id,
                            path,
                            plugin_dir=manifest.plugin_dir,
                            connection_id=connection_id,
                        )
                    )
                if hooks:
                    from ..hooks.contracts import HookEventType

                    registry = self._hook_registry_provider()
                    if registry is None:
                        raise RuntimeError("Plugin hook registry is unavailable")
                    seen_hooks: set[tuple[Any, int]] = set()
                    for index, raw in enumerate(hooks):
                        event_type, handler, matcher = _parse_hook_spec(
                            raw, event_type_cls=HookEventType
                        )
                        key = (event_type, id(handler))
                        if key in seen_hooks:
                            raise ValueError(f"Duplicate hook handler: {event_type.value}")
                        seen_hooks.add(key)

                        # A distinct wrapper prevents one owner's registration from changing
                        # another owner's matcher/source metadata for the same callable.
                        async def owned_handler(context: Any, _handler: Any = handler) -> Any:
                            return await _handler(context)

                        registry.register(
                            event_type,
                            owned_handler,
                            matcher=matcher,
                            source=f"plugin:{plugin_id}:{connection_id}",
                        )
                        disposers.append(
                            lambda r=registry, e=event_type, h=owned_handler: r.unregister(e, h)
                        )
                        record(
                            ContributionType.HOOK,
                            f"hook:{event_type.value}:{index}",
                            display_name=f"{event_type.value} hook",
                            description="",
                            surface="extensions",
                            metadata={"event_type": event_type.value, "matcher": matcher},
                        )
                return contributions
            except BaseException:
                self.unregister(connection_id)
                raise

    def unregister(self, connection_id: str) -> None:
        """Dispose exact entries in reverse order, retaining failed cleanup for retry."""
        with self._lock:
            disposers = self._registrations.get(connection_id)
            if disposers is None:
                return
            failures: list[Exception] = []
            for dispose in tuple(reversed(disposers)):
                try:
                    dispose()
                except Exception as exc:
                    failures.append(exc)
                else:
                    disposers.remove(dispose)
            if failures:
                raise RuntimeError(
                    f"Contribution cleanup failed for {connection_id}: {failures}"
                ) from failures[0]
            self._registrations.pop(connection_id, None)


def _parse_hook_spec(spec: Any, *, event_type_cls: Any) -> tuple[Any, Any, str | None]:
    if not isinstance(spec, tuple) or len(spec) not in {2, 3}:
        raise ValueError("Hook contribution must be an event, handler, and optional matcher tuple")
    event_type = event_type_cls(spec[0])
    handler = spec[1]
    if not asyncio.iscoroutinefunction(handler):
        raise TypeError(f"Hook handler for {event_type.value} must be async")
    matcher = spec[2] if len(spec) == 3 else None
    if matcher is not None and not isinstance(matcher, str):
        raise TypeError("Hook matcher must be a string or None")
    return event_type, handler, matcher


def _resolve_hook_registry() -> Any | None:
    from ..core.container import get_container

    registry = get_container().hook_registry()
    return None if registry is None or type(registry).__name__ == "object" else registry
