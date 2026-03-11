"""Sensor contribution contracts and registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .contracts import ExtensionFieldSpec, PluginContribution


@dataclass(slots=True)
class SensorSpec:
    """Declarative metadata for a sensor contribution."""

    sensor_id: str
    display_name: str
    description: str = ""
    domain: str = "general"
    surface: str = "extensions"
    sync_mode: str = "manual"
    polling_mode: str = "manual"
    fields: list[ExtensionFieldSpec] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class SensorRegistry:
    """Registry for runtime sensor contributions."""

    def __init__(self) -> None:
        self._sensors: dict[str, Any] = {}
        self._specs: dict[str, SensorSpec] = {}
        self._plugin_ownership: dict[str, str] = {}

    def register(self, plugin_id: str, sensor_id: str, sensor: Any, spec: SensorSpec) -> None:
        self._sensors[sensor_id] = sensor
        self._specs[sensor_id] = spec
        self._plugin_ownership[sensor_id] = plugin_id

    def unregister(self, sensor_id: str) -> None:
        self._sensors.pop(sensor_id, None)
        self._specs.pop(sensor_id, None)
        self._plugin_ownership.pop(sensor_id, None)

    def get_sensor(self, sensor_id: str) -> Optional[Any]:
        return self._sensors.get(sensor_id)

    def get_spec(self, sensor_id: str) -> Optional[SensorSpec]:
        return self._specs.get(sensor_id)

    def list_specs(self, *, domain: Optional[str] = None) -> list[SensorSpec]:
        specs = list(self._specs.values())
        if domain is not None:
            specs = [spec for spec in specs if spec.domain == domain]
        return specs

    def resolve_domain_sensor(self, domain: str, source_type: str) -> tuple[str, str, Any, SensorSpec] | None:
        for sensor_id, sensor in self._sensors.items():
            spec = self._specs[sensor_id]
            candidate = str(spec.metadata.get("source_type") or getattr(sensor, "source_type", ""))
            if spec.domain == domain and candidate == source_type:
                return self._plugin_ownership.get(sensor_id, ""), sensor_id, sensor, spec
        return None

    def list_contributions(self, plugin_id: Optional[str] = None) -> list[PluginContribution]:
        contributions: list[PluginContribution] = []
        for sensor_id, spec in self._specs.items():
            owner = self._plugin_ownership.get(sensor_id, "")
            if plugin_id is not None and owner != plugin_id:
                continue
            contributions.append(
                PluginContribution(
                    plugin_id=owner,
                    contribution_id=sensor_id,
                    contribution_type="sensor",
                    display_name=spec.display_name,
                    description=spec.description,
                    surface=spec.surface if spec.surface in {"extensions", "tools", "timeline", "actions"} else "extensions",
                    fields=list(spec.fields),
                    metadata={
                        "domain": spec.domain,
                        "sync_mode": spec.sync_mode,
                        "polling_mode": spec.polling_mode,
                        **dict(spec.metadata),
                    },
                )
            )
        return contributions
