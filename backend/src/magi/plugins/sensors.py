"""Sensor contribution contracts and registry."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
import threading
from typing import Any, Optional

from .contracts import PluginContribution
from magi_plugin_sdk.sensors import SensorSpec  # noqa: F401


@dataclass(frozen=True, slots=True)
class RegisteredSensorSnapshot:
    """Stable identity and instance for one registered sensor contribution."""

    plugin_id: str
    sensor_id: str
    sensor: Any
    connection_id: str | None = None


class SensorRegistry:
    """Registry for runtime sensor contributions."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sensors: dict[str, Any] = {}
        self._specs: dict[str, SensorSpec] = {}
        self._plugin_ownership: dict[str, str] = {}
        self._registration_tokens: dict[str, object] = {}

    def register(
        self, plugin_id: str, sensor_id: str, sensor: Any, spec: SensorSpec
    ) -> Callable[[], None]:
        if sensor_id != spec.sensor_id:
            raise ValueError("Sensor tuple id must match its spec")
        token = object()
        with self._lock:
            if sensor_id in self._sensors:
                raise ValueError(f"Sensor already registered: {sensor_id}")
            self._sensors[sensor_id] = sensor
            self._specs[sensor_id] = spec
            self._plugin_ownership[sensor_id] = plugin_id
            self._registration_tokens[sensor_id] = token

        def dispose() -> None:
            with self._lock:
                if self._registration_tokens.get(sensor_id) is token:
                    self.unregister(sensor_id, plugin_id=plugin_id)

        return dispose

    def unregister(self, sensor_id: str, *, plugin_id: str) -> bool:
        with self._lock:
            if self._plugin_ownership.get(sensor_id) != plugin_id:
                return False
            self._sensors.pop(sensor_id, None)
            self._specs.pop(sensor_id, None)
            self._plugin_ownership.pop(sensor_id, None)
            self._registration_tokens.pop(sensor_id, None)
            return True

    def get_sensor(self, sensor_id: str) -> Optional[Any]:
        with self._lock:
            return self._sensors.get(sensor_id)

    def get_spec(self, sensor_id: str) -> Optional[SensorSpec]:
        with self._lock:
            return self._specs.get(sensor_id)

    def list_specs(self, *, domain: Optional[str] = None) -> list[SensorSpec]:
        with self._lock:
            specs = list(self._specs.values())
        if domain is not None:
            specs = [spec for spec in specs if spec.domain == domain]
        return specs

    def resolve_domain_sensor(
        self, domain: str, source_type: str, *, connection_id: str | None = None
    ) -> tuple[str, str, Any, SensorSpec] | None:
        with self._lock:
            matches = []
            for sensor_id, sensor in self._sensors.items():
                spec = self._specs[sensor_id]
                candidate = str(
                    spec.metadata.get("source_type") or getattr(sensor, "source_type", "")
                )
                if (
                    spec.domain == domain
                    and candidate == source_type
                    and (
                        connection_id is None or spec.metadata.get("connection_id") == connection_id
                    )
                ):
                    matches.append(
                        (self._plugin_ownership.get(sensor_id, ""), sensor_id, sensor, spec)
                    )
            if len(matches) > 1:
                raise ValueError("Domain sensor lookup requires an unambiguous connection id")
            return matches[0] if matches else None

    def resolve_source_sensor(
        self, source_type: str, *, connection_id: str | None = None
    ) -> tuple[str, str, Any, SensorSpec] | None:
        with self._lock:
            matches = []
            for sensor_id, sensor in self._sensors.items():
                spec = self._specs[sensor_id]
                candidate = str(
                    spec.metadata.get("source_type") or getattr(sensor, "source_type", "")
                )
                if candidate == source_type and (
                    connection_id is None or spec.metadata.get("connection_id") == connection_id
                ):
                    matches.append(
                        (self._plugin_ownership.get(sensor_id, ""), sensor_id, sensor, spec)
                    )
            if len(matches) > 1:
                raise ValueError("Source sensor lookup requires an unambiguous connection id")
            return matches[0] if matches else None

    def list_contributions(self, plugin_id: Optional[str] = None) -> list[PluginContribution]:
        with self._lock:
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
                        surface=spec.surface
                        if spec.surface in {"extensions", "tools", "timeline"}
                        else "extensions",
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

    def snapshot_user_content_clear_targets(self) -> tuple[RegisteredSensorSnapshot, ...]:
        """Return a stable sensor snapshot for one host clear operation."""

        with self._lock:
            return tuple(
                RegisteredSensorSnapshot(
                    plugin_id=self._plugin_ownership.get(sensor_id, ""),
                    sensor_id=sensor_id,
                    sensor=sensor,
                    connection_id=self._specs[sensor_id].metadata.get("connection_id"),
                )
                for sensor_id, sensor in sorted(self._sensors.items())
            )


__all__ = ["RegisteredSensorSnapshot", "SensorRegistry", "SensorSpec"]
