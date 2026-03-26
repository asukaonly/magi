"""Timeline event handler — builds the async handler that processes timeline payloads."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from ..config import AppConfig
from ..memory import UnifiedMemoryStore
from ..plugins import PluginManager, SensorRegistry
from .service import TimelineService

if TYPE_CHECKING:
    from ..awareness.ingestion_gateway import SensorIngestionGateway


def _get_nested_setting(payload: dict[str, Any], path: str, default: Any) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return default
        if part not in current:
            return default
        current = current[part]
    return current


def build_timeline_handler(
    config: AppConfig,
    unified_memory: UnifiedMemoryStore,
    *,
    sensor_registry: SensorRegistry,
    plugin_manager: PluginManager,
    ingestion_gateway: SensorIngestionGateway | None = None,
) -> Callable[[dict[str, Any]], Any]:
    """Build an async handler that processes incoming timeline payloads."""
    service = TimelineService(unified_memory)

    async def _handle_timeline_payload(payload: dict[str, Any]) -> dict[str, Any]:
        source_type = str(payload.get("source_type") or "").strip()
        resolved = sensor_registry.resolve_domain_sensor("timeline", source_type)
        if resolved is None:
            return {"handled": False, "reason": "unsupported_source", "source_type": source_type}
        plugin_id, _sensor_id, sensor, spec = resolved
        package_state = plugin_manager.get_package(plugin_id)
        current_settings = package_state.current_settings if package_state is not None else {}
        sensor_settings_path = f"sensors.{source_type}"
        default_settings = dict(spec.metadata.get("default_settings", {}))
        if not bool(
            _get_nested_setting(
                current_settings,
                f"{sensor_settings_path}.enabled",
                default_settings.get("enabled", True),
            )
        ):
            return {"handled": False, "reason": "source_disabled", "source_type": source_type}

        allowed_edge_whitelist = [
            str(edge_type)
            for edge_type in _get_nested_setting(
                current_settings,
                f"{sensor_settings_path}.edge_whitelist",
                default_settings.get("edge_whitelist", []),
            )
        ]

        if ingestion_gateway is not None:
            # New path: SensorBase.build_output → SensorIngestionGateway
            output = await sensor.build_output(payload)
            metadata = await sensor.extract_metadata(payload)
            output.provenance.update(
                {
                    "correlation_id": str(payload.get("correlation_id") or ""),
                    "timeline_task_agent_id": str(payload.get("target_task_agent_id") or ""),
                }
            )
            result = await ingestion_gateway.ingest(
                sensor, output, metadata,
                allowed_edge_whitelist=allowed_edge_whitelist,
            )
            return {"handled": True, "event_id": result.event_id, "source_type": source_type}

        # Legacy fallback
        event = await sensor.build_timeline_event(payload)
        extracted = await sensor.extract_candidates(payload)
        event.entities = list(extracted.get("entities", []))
        event.tags = list(dict.fromkeys([*event.tags, *list(extracted.get("tags", []))]))
        event.provenance.update(
            {
                "correlation_id": str(payload.get("correlation_id") or ""),
                "timeline_task_agent_id": str(payload.get("target_task_agent_id") or ""),
            }
        )
        await service.upsert_event(
            event,
            relation_candidates=list(extracted.get("relation_candidates", [])),
            allowed_edge_whitelist=allowed_edge_whitelist,
        )
        return {"handled": True, "event_id": event.event_id, "source_type": source_type}

    return _handle_timeline_payload
