"""Timeline event handler — builds the async handler that processes timeline payloads."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from ..config import AppConfig
from magi_plugin_sdk.runtime import SourceChange, SourceChangeBatch
from ..awareness.source_ingestion import SourceBatchIngestor
from ..awareness.source_store import SourceStore
from ..plugins.operation_execution import plugin_runtime_operation
from ..utils.runtime import get_runtime_paths
from ..memory import UnifiedMemoryStore
from ..plugins import PluginManager, SourceRegistry

if TYPE_CHECKING:
    from ..awareness.ingestion_gateway import SourceIngestionGateway


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
    source_registry: SourceRegistry,
    plugin_manager: PluginManager,
    ingestion_gateway: SourceIngestionGateway | None = None,
) -> Callable[[dict[str, Any]], Any]:
    """Build an async handler that processes incoming timeline payloads."""

    async def _handle_timeline_payload(payload: dict[str, Any]) -> dict[str, Any]:
        async with plugin_runtime_operation():
            return await _handle_admitted_payload(payload)

    async def _handle_admitted_payload(payload: dict[str, Any]) -> dict[str, Any]:
        connection_id = str(payload.get("connection_id") or "").strip()
        if not connection_id:
            raise ValueError("Timeline source ingestion requires an explicit connection identity")
        change = SourceChange.model_validate(payload.get("source_change"))
        source_type = str(payload.get("source_type") or "").strip()
        resolved = source_registry.resolve_source(source_type, connection_id=connection_id)
        if resolved is None:
            return {"handled": False, "reason": "unsupported_source", "source_type": source_type}
        plugin_id, _source_id, source, spec = resolved
        package_state = plugin_manager.get_package(plugin_id)
        if package_state is None or source.connection is None or not source.connection.enabled:
            return {"handled": False, "reason": "source_disabled", "source_type": source_type}
        if spec.domain != "timeline":
            return {"handled": False, "reason": "unsupported_source", "source_type": source_type}
        current_settings = source.connection.settings
        source_settings_path = f"sources.{source_type}"
        default_settings = dict(spec.metadata.get("default_settings", {}))
        if not bool(
            _get_nested_setting(
                current_settings,
                f"{source_settings_path}.enabled",
                default_settings.get("enabled", True),
            )
        ):
            return {"handled": False, "reason": "source_disabled", "source_type": source_type}

        allowed_edge_whitelist = [
            str(edge_type)
            for edge_type in _get_nested_setting(
                current_settings,
                f"{source_settings_path}.edge_whitelist",
                default_settings.get("edge_whitelist", []),
            )
        ]

        if ingestion_gateway is None:
            raise RuntimeError("SourceIngestionGateway is required for timeline event handling")

        store = SourceStore(get_runtime_paths().runtime_dir / "plugin_sources.db")
        checkpoint = await store.checkpoint(source.connection, source.source_id, source_type)
        boundary = await ingestion_gateway.capture_ingestion_boundary()
        pending = await store.stage_batch(
            source.connection, checkpoint,
            SourceChangeBatch(changes=[change], next_cursor=checkpoint.cursor),
        )
        await SourceBatchIngestor(store=store, gateway=ingestion_gateway).ingest(
            connection=source.connection, source=source, pending=pending, boundary=boundary,
            rule_revision=package_state.manifest.version, allowed_edge_whitelist=allowed_edge_whitelist,
            provenance={
                "correlation_id": str(payload.get("correlation_id") or ""),
                "timeline_task_agent_id": str(payload.get("target_task_agent_id") or ""),
            },
        )
        version = await store.version(checkpoint, change)
        return {"handled": True, "event_id": (version["receipt"] or {}).get("event_id"),
                "source_type": source_type, "connection_id": connection_id}

    return _handle_timeline_payload
