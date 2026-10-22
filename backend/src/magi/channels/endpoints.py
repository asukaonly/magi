"""Channel-owned endpoint discovery and explicit delivery preferences."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from magi_plugin_sdk.endpoints import EndpointRef

from ..config import get_user_preference, save_config


class EndpointCatalog:
    """Join known conversation bindings and output device discovery."""

    def __init__(self, registry: Any, session_mapper: Any) -> None:
        self._registry = registry
        self._mapper = session_mapper

    async def list_endpoints(self) -> list[dict[str, Any]]:
        result = []
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
                continue
            connection, separator, contribution = channel.channel_type.partition(":")
            for device in devices:
                endpoint = EndpointRef(
                    connection if separator else None, contribution if separator else connection,
                    device.target.target_id,
                )
                result.append({
                    "endpoint": endpoint.to_dict(), "label": device.label,
                    "capabilities": ["audio"], "available": device.available,
                })
        return result

    @staticmethod
    def delivery_preferences() -> list[dict[str, Any]]:
        return [EndpointRef.from_dict(value).to_dict()
                for value in get_user_preference("delivery_targets", [])]

    async def set_delivery_preferences(self, values: list[dict[str, Any]]) -> None:
        if len(values) > 32:
            raise ValueError("At most 32 delivery destinations are allowed")
        targets = tuple(EndpointRef.from_dict(value) for value in values)
        if len(set(targets)) != len(targets):
            raise ValueError("Delivery destinations must be unique")
        known = {EndpointRef.from_dict(item["endpoint"]) for item in await self.list_endpoints()
                 if "message" in item["capabilities"]}
        if any(target not in known for target in targets):
            raise ValueError("Delivery destinations must be known messaging endpoints")
        if not save_config({"preferences.delivery_targets": [target.to_dict() for target in targets]}):
            raise RuntimeError("Failed to persist delivery destinations")
