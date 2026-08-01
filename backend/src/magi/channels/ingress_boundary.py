"""Destructive-clear admission boundary for external channel messages."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from magi_plugin_sdk.channels import (
    ChannelCursorClearProof,
    ChannelInboundContext,
    ChannelInboundEvidence,
    ChannelInboundRejectedError,
    ChannelInboundRejectionReason,
    ChannelProviderTimeEvidence,
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
        channel_type: str,
        stream_id: str,
        evidence: ChannelInboundEvidence,
    ) -> ChannelInboundContext:
        """Capture the durable clear generation before any inbound mutation."""

        normalized_channel_type = _normalize_identifier(
            channel_type,
            label="Channel type",
        )
        normalized_stream_id = _normalize_identifier(
            stream_id,
            label="Channel stream ID",
        )
        evidence_kwargs = _evidence_arguments(evidence)
        try:
            generation = (
                await self._runtime_command_queue.capture_external_user_message_context(
                    **evidence_kwargs,
                )
            )
        except InvalidExternalUserMessageMetadataError as exc:
            raise _invalid_metadata_error(str(exc)) from exc
        except StaleExternalUserMessageError as exc:
            raise _cleared_message_error(str(exc)) from exc
        return ChannelInboundContext(
            channel_type=normalized_channel_type,
            stream_id=normalized_stream_id,
            admission_evidence=evidence,
            clear_generation=generation,
        )

    async def read_current_clear_generation(self) -> int:
        """Expose the durable host clear generation without mutation access."""

        return int(
            await self._runtime_command_queue.read_current_clear_generation()
        )

    @asynccontextmanager
    async def operation(
        self,
        inbound_context: ChannelInboundContext,
        *,
        expected_channel_type: str | None = None,
    ) -> AsyncIterator[None]:
        """Revalidate one host mutation and keep it atomic with respect to clear."""

        if not isinstance(inbound_context, ChannelInboundContext):
            raise _invalid_metadata_error(
                "A host-issued channel inbound context is required"
            )
        context_channel_type = _normalize_identifier(
            inbound_context.channel_type,
            label="Channel type",
        )
        _normalize_identifier(
            inbound_context.stream_id,
            label="Channel stream ID",
        )
        if expected_channel_type is not None:
            normalized_expected_channel_type = _normalize_identifier(
                expected_channel_type,
                label="Expected channel type",
            )
            if context_channel_type != normalized_expected_channel_type:
                raise _invalid_metadata_error(
                    "Channel inbound context does not match the target channel"
                )
        evidence_kwargs = _evidence_arguments(
            inbound_context.admission_evidence
        )
        try:
            async with self._runtime_command_queue.external_user_message_operation(
                captured_generation=inbound_context.clear_generation,
                **evidence_kwargs,
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


def _normalize_identifier(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid_metadata_error(f"{label} must be a non-empty string")
    return value.strip()


def _evidence_arguments(evidence: object) -> dict[str, object]:
    if isinstance(evidence, ChannelProviderTimeEvidence):
        return {"provider_occurred_at_ms": evidence.provider_occurred_at_ms}
    if isinstance(evidence, ChannelCursorClearProof):
        return {"cursor_clear_generation": evidence.clear_generation}
    raise _invalid_metadata_error(
        "Channel inbound evidence must contain provider time or a cursor proof"
    )


def _cleared_message_error(message: str) -> ChannelInboundRejectedError:
    return ChannelInboundRejectedError(
        ChannelInboundRejectionReason.CLEARED_MESSAGE,
        message,
    )


__all__ = ["ChannelIngressBoundary"]
