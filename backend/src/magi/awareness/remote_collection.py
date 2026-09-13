"""Adapt device observations into the source-owned ingestion pipeline."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from magi_plugin_sdk.ingress import PluginIngressHandlerRegistration, IngressProcessingError
from magi_plugin_sdk.runtime import SourceChange


class _SourceIngress:
    def __init__(self, connection_id: str, source_types: set[str], get_contributor: Callable[[], Any]) -> None:
        self.connection_id = connection_id
        self.source_types = source_types
        self.get_contributor = get_contributor

    async def handle_event(self, event: Any, payload: dict[str, Any]) -> None:
        source_type = payload.get("source_type")
        if source_type not in self.source_types or set(payload) != {"source_type", "plugin_version", "source_change"}:
            raise ValueError("Invalid collector source envelope")
        contributor = self.get_contributor()
        if contributor is None:
            raise IngressProcessingError("temporarily_unavailable")
        await contributor.ingest_collector_change(
            connection_id=self.connection_id, source_type=source_type,
            client_id=event.producer.split(":", 1)[0], plugin_version=payload["plugin_version"],
            change=SourceChange.model_validate(payload["source_change"]),
        )


def source_ingress_registrations(connection_id: str, plugin_id: str, sources: list[Any],
                                 get_contributor: Callable[[], Any]) -> list[PluginIngressHandlerRegistration]:
    """Only explicitly portable, resource-free sources may accept collector payloads."""
    types = {str(spec.metadata["source_type"]) for _, source, spec in sources
             if spec.metadata.get("remote_collection") == "source.change.v1"
             and not bool(getattr(source, "supports_watch_mode", False))}
    if not types:
        return []
    return [PluginIngressHandlerRegistration(plugin_id, "source.change.v1",
            _SourceIngress(connection_id, types, get_contributor), replay_safe=True)]
