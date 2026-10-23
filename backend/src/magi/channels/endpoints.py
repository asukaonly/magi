"""Channel-owned endpoint discovery and explicit delivery preferences."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from magi_plugin_sdk.endpoints import EndpointRef

from ..delivery.outbox import DeliveryOutbox, DeliveryStatus

from ..config import get_user_preference, save_config


class EndpointCatalog:
    """Join known conversation bindings and output device discovery."""

    def __init__(self, registry: Any, session_mapper: Any, outbox: DeliveryOutbox | None = None) -> None:
        self._registry = registry
        self._mapper = session_mapper
        self._outbox = outbox
        self._audio_endpoints: dict[str, list[dict[str, Any]]] = {}

    async def list_endpoints(self) -> list[dict[str, Any]]:
        result, _ = await self._discover_endpoints()
        return result

    async def _discover_endpoints(self) -> tuple[list[dict[str, Any]], set[str]]:
        result = []
        unavailable: set[str] = set()
        for mapping in await self._mapper.list_all():
            connection, separator, contribution = mapping.channel_type.partition(":")
            endpoint = EndpointRef(
                connection if separator else None, contribution if separator else connection,
                mapping.external_chat_id, mapping.external_thread_id,
            )
            try:
                metadata = json.loads(mapping.metadata_json or "{}")
            except (ValueError, TypeError):
                metadata = {}
            label = metadata.get("display_name") if isinstance(metadata, dict) else None
            channel = self._registry.get(mapping.channel_type)
            capabilities = ["message"]
            if channel is not None and channel.supports_control_requests:
                capabilities.append("control")
            result.append({
                "endpoint": endpoint.to_dict(), "label": str(label or mapping.external_chat_id),
                "capabilities": capabilities, "available": channel is not None,
            })
        for channel in self._registry.all_audio_channels():
            # One unavailable provider must not hide every other known endpoint.
            try:
                devices = await asyncio.wait_for(channel.list_targets(), timeout=5)
            except Exception:
                unavailable.add(channel.channel_type)
                result.extend({**item, "available": False}
                              for item in self._audio_endpoints.get(channel.channel_type, []))
                continue
            connection, separator, contribution = channel.channel_type.partition(":")
            discovered = []
            for device in devices:
                endpoint = EndpointRef(
                    connection if separator else None, contribution if separator else connection,
                    device.target.target_id,
                )
                discovered.append({
                    "endpoint": endpoint.to_dict(), "label": device.label,
                    "capabilities": ["audio"], "available": device.available,
                })
            self._audio_endpoints[channel.channel_type] = discovered
            result.extend(discovered)
        return result, unavailable

    @staticmethod
    def delivery_preferences() -> list[dict[str, Any]]:
        return [EndpointRef.from_dict(value).to_dict()
                for value in get_user_preference("delivery_targets", [])]

    async def set_delivery_preferences(self, values: list[dict[str, Any]]) -> None:
        if len(values) > 32:
            raise ValueError("At most 32 delivery destinations are allowed")
        targets = tuple(EndpointRef.from_dict(value) for value in values)
        await self.validate_delivery_targets(targets)
        if not save_config({"preferences.delivery_targets": [target.to_dict() for target in targets]}):
            raise RuntimeError("Failed to persist delivery destinations")

    async def validate_delivery_targets(self, targets: tuple[EndpointRef, ...]) -> None:
        if len(targets) > 32:
            raise ValueError("At most 32 delivery destinations are allowed")
        if len(set(targets)) != len(targets):
            raise ValueError("Delivery destinations must be unique")
        endpoints, unavailable = await self._discover_endpoints()
        known = {EndpointRef.from_dict(item["endpoint"]) for item in endpoints
                 if set(item["capabilities"]) & {"message", "audio"}}
        if any(target not in known and target.registry_key in unavailable for target in targets):
            raise RuntimeError("Delivery destination discovery is unavailable")
        if any(target not in known for target in targets):
            raise ValueError("Delivery destinations must be known output endpoints")

    async def delivery_status(self) -> list[DeliveryStatus]:
        if self._outbox is None:
            raise RuntimeError("Delivery status is not ready")
        return await self._outbox.list_recent_outbound_status()
