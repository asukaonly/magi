"""Clear-aware adapter for channel-owned inbound attachments."""

from __future__ import annotations

from typing import Any

from magi_plugin_sdk.channels import (
    ChannelInboundContext,
)

from .ingress_boundary import ChannelIngressBoundary


class GuardedChannelAttachmentStore:
    """Protect the chat attachment store with the channel ingress boundary."""

    def __init__(
        self,
        *,
        delegate: Any,
        ingress_boundary: ChannelIngressBoundary,
    ) -> None:
        self._delegate = delegate
        self._ingress_boundary = ingress_boundary

    async def store_attachment(
        self,
        *,
        inbound_context: ChannelInboundContext,
        session_id: str,
        turn_id: str,
        kind: str,
        original_name: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        async with self._ingress_boundary.operation(inbound_context):
            result = await self._delegate.store_attachment(
                session_id=session_id,
                turn_id=turn_id,
                kind=kind,
                original_name=original_name,
                content=content,
                mime_type=mime_type,
            )
            if not isinstance(result, dict):
                raise TypeError("Channel attachment store returned an invalid payload")
            return dict(result)


__all__ = ["GuardedChannelAttachmentStore"]
