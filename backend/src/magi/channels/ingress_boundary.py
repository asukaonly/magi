"""Destructive-clear admission boundary for external channel messages."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from magi_plugin_sdk.channels import (
    ChannelInboundContext,
    ChannelInboundRejectedError,
    ChannelInboundRejectionReason,
)

from ..events.runtime_queue import (
    InvalidExternalUserMessageMetadataError,
    StaleExternalUserMessageError,
)


class ChannelIngressBoundary:
    """Issue and validate host-owned admission contexts for channel ingress."""

    def __init__(self, *, runtime_command_queue: Any) -> None:
        self._runtime_command_queue = runtime_command_queue

    async def capture(
        self,
        *,
        provider_occurred_at_ms: int,
    ) -> ChannelInboundContext:
        """Capture the durable clear generation before any inbound mutation."""

        try:
            generation = (
                await self._runtime_command_queue.capture_external_user_message_context(
                    provider_occurred_at_ms=provider_occurred_at_ms,
                )
            )
        except InvalidExternalUserMessageMetadataError as exc:
            raise _invalid_metadata_error(str(exc)) from exc
        except StaleExternalUserMessageError as exc:
            raise _cleared_message_error(str(exc)) from exc
        return ChannelInboundContext(
            provider_occurred_at_ms=provider_occurred_at_ms,
            clear_generation=generation,
        )

    @asynccontextmanager
    async def operation(
        self,
        inbound_context: ChannelInboundContext,
    ) -> AsyncIterator[None]:
        """Revalidate one host mutation and keep it atomic with respect to clear."""

        if not isinstance(inbound_context, ChannelInboundContext):
            raise _invalid_metadata_error(
                "A host-issued channel inbound context is required"
            )
        try:
            async with self._runtime_command_queue.external_user_message_operation(
                provider_occurred_at_ms=inbound_context.provider_occurred_at_ms,
                captured_generation=inbound_context.clear_generation,
            ):
                yield
        except InvalidExternalUserMessageMetadataError as exc:
            raise _invalid_metadata_error(str(exc)) from exc
        except StaleExternalUserMessageError as exc:
            raise _cleared_message_error(str(exc)) from exc


def _invalid_metadata_error(message: str) -> ChannelInboundRejectedError:
    return ChannelInboundRejectedError(
        ChannelInboundRejectionReason.INVALID_METADATA,
        message,
    )


def _cleared_message_error(message: str) -> ChannelInboundRejectedError:
    return ChannelInboundRejectedError(
        ChannelInboundRejectionReason.CLEARED_MESSAGE,
        message,
    )


__all__ = ["ChannelIngressBoundary"]
