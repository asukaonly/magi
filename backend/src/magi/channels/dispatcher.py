"""Inbound message dispatch adapter for channel plugins.

Phase H+2: control-command short-circuit. If the inbound message
parses as ``/approve <short_id>`` or ``/deny <short_id>``, the
dispatcher resolves the pending permission via the broker and
returns success WITHOUT going through ``dispatch_user_message`` —
the LLM never sees the slash command. Falls through to normal
dispatch for any other message.
"""
from __future__ import annotations

import hashlib
import json

from magi_plugin_sdk.channels import (
    ChannelCursorClearProof,
    ChannelInboundClearStrategy,
    ChannelInboundContext,
    ChannelInboundEvidence,
    ChannelInboundRejectedError,
    ChannelInboundRejectionReason,
    ChannelMessageDispatcherProtocol,
    ChannelMessageDispatchOutcome,
    ChannelProviderTimeEvidence,
)

from ..core.runtime_bindings import require_user_message_dispatcher
from ..control.permission.slash_commands import try_handle_control_command
from .ingress_boundary import ChannelIngressBoundary
from .session_commands import try_handle_session_command


MESSAGE_DISPATCHER_NOT_INITIALIZED = "MESSAGE_DISPATCHER_NOT_INITIALIZED"
_EXTERNAL_TURN_PREFIX = "turn_external_"


class ChannelMessageDispatcher(ChannelMessageDispatcherProtocol):
    """Adapt the backend message dispatch service to the channel SDK contract."""

    def __init__(
        self,
        *,
        channel_type: str,
        inbound_clear_strategy: ChannelInboundClearStrategy,
        ingress_boundary: ChannelIngressBoundary,
        permission_registry: object | None = None,
        interaction_broker: object | None = None,
        session_mapper: object | None = None,
        message_dispatcher: object | None = None,
    ) -> None:
        normalized_channel_type = str(channel_type or "").strip()
        if not normalized_channel_type:
            raise ValueError("Channel message dispatcher requires a channel type")
        if inbound_clear_strategy not in (
            ChannelInboundClearStrategy.PROVIDER_TIME,
            ChannelInboundClearStrategy.DURABLE_CURSOR,
        ):
            raise ValueError(
                "External channel dispatcher requires an external clear strategy"
            )
        self._channel_type = normalized_channel_type
        self._inbound_clear_strategy = inbound_clear_strategy
        self._ingress_boundary = ingress_boundary
        # Optional Phase H+2 wiring — when both are provided, inbound
        # messages are checked for /approve|/deny slash commands before
        # being dispatched to the LLM. When None (legacy / tests that
        # don't care about control commands), the slash-command path
        # is disabled and every message dispatches normally.
        self._permission_registry = permission_registry
        self._interaction_broker = interaction_broker
        # When provided, inbound messages are also checked for the
        # new-session command (/新会话 …), which resets the channel→session
        # binding so the next message starts fresh. None disables it.
        self._session_mapper = session_mapper
        self._message_dispatcher = message_dispatcher

    async def capture_inbound_context(
        self,
        *,
        channel_type: str,
        stream_id: str,
        evidence: ChannelInboundEvidence,
    ) -> ChannelInboundContext:
        """Capture the host clear generation before any inbound side effect."""

        if str(channel_type or "").strip() != self._channel_type:
            raise _invalid_inbound_metadata(
                "Channel dispatcher cannot capture another channel's event"
            )
        if (
            self._inbound_clear_strategy
            is ChannelInboundClearStrategy.PROVIDER_TIME
            and not isinstance(evidence, ChannelProviderTimeEvidence)
        ):
            raise _invalid_inbound_metadata(
                "Provider-time channel requires provider occurrence evidence"
            )
        if (
            self._inbound_clear_strategy
            is ChannelInboundClearStrategy.DURABLE_CURSOR
            and not isinstance(evidence, ChannelCursorClearProof)
        ):
            raise _invalid_inbound_metadata(
                "Durable-cursor channel requires an applied cursor generation"
            )
        return await self._ingress_boundary.capture(
            channel_type=channel_type,
            stream_id=stream_id,
            evidence=evidence,
        )

    async def read_current_clear_generation(self) -> int:
        """Return the current durable clear generation to a channel plugin."""

        return await self._ingress_boundary.read_current_clear_generation()

    async def dispatch_user_message(
        self,
        *,
        inbound_context: ChannelInboundContext,
        source: str,
        user_id: str,
        message: str,
        session_id: str | None = None,
        attachments: list[dict[str, object]] | None = None,
        reply_to_message_id: str | None = None,
        workspace_path: str | None = None,
        client_turn_id: str | None = None,
        metadata: dict[str, object] | None = None,
        runtime_namespace: str | None = None,
    ) -> ChannelMessageDispatchOutcome:
        async with self._ingress_boundary.operation(
            inbound_context,
            expected_channel_type=source,
        ):
            command_outcome = await self._try_handle_channel_command(
                user_id=user_id,
                session_id=session_id,
                message=message,
            )
            if command_outcome is not None:
                return command_outcome

            message_dispatcher, dispatcher_error = self._resolve_message_dispatcher(
                user_id=user_id,
                session_id=session_id,
            )
            if dispatcher_error is not None:
                return dispatcher_error

            controlled_metadata = dict(metadata or {})
            controlled_metadata.pop("provider_occurred_at_ms", None)
            controlled_metadata.pop("channel_cursor_clear_generation", None)
            controlled_metadata["channel_type"] = inbound_context.channel_type
            controlled_metadata["channel_stream_id"] = inbound_context.stream_id
            controlled_metadata["channel_clear_generation"] = (
                inbound_context.clear_generation
            )
            if isinstance(
                inbound_context.admission_evidence,
                ChannelProviderTimeEvidence,
            ):
                controlled_metadata["provider_occurred_at_ms"] = (
                    inbound_context.admission_evidence.provider_occurred_at_ms
                )
            elif isinstance(
                inbound_context.admission_evidence,
                ChannelCursorClearProof,
            ):
                controlled_metadata["channel_cursor_clear_generation"] = (
                    inbound_context.admission_evidence.clear_generation
                )
            outcome = await message_dispatcher(
                source=source,
                user_id=user_id,
                message=message,
                session_id=session_id,
                attachments=attachments,
                reply_to_message_id=reply_to_message_id,
                workspace_path=workspace_path,
                client_turn_id=_resolve_client_turn_id(
                    source=source,
                    client_turn_id=client_turn_id,
                    metadata=controlled_metadata,
                ),
                metadata=controlled_metadata,
                runtime_namespace=runtime_namespace,
            )
            return _channel_dispatch_outcome(outcome)

    async def _try_handle_channel_command(
        self,
        *,
        user_id: str,
        session_id: str | None,
        message: str,
    ) -> ChannelMessageDispatchOutcome | None:
        control_outcome = await self._try_handle_permission_command(message, session_id)
        if control_outcome is not None:
            return _control_command_outcome(
                user_id=user_id,
                session_id=session_id,
                ack_message=control_outcome,
            )
        session_outcome = await self._try_handle_session_command(message, session_id)
        if session_outcome is None:
            return None
        return _control_command_outcome(
            user_id=user_id,
            session_id=session_id,
            ack_message=session_outcome,
        )

    async def _try_handle_permission_command(
        self,
        message: str,
        session_id: str | None,
    ) -> str | None:
        if self._permission_registry is None or self._interaction_broker is None:
            return None
        outcome = await try_handle_control_command(
            message=message,
            session_id=session_id,
            registry=self._permission_registry,  # type: ignore[arg-type]
            broker=self._interaction_broker,  # type: ignore[arg-type]
        )
        return outcome.ack_message if outcome.handled else None

    async def _try_handle_session_command(
        self,
        message: str,
        session_id: str | None,
    ) -> str | None:
        if self._session_mapper is None:
            return None
        outcome = await try_handle_session_command(
            message=message,
            session_id=session_id,
            session_mapper=self._session_mapper,
        )
        return outcome.ack_message if outcome.handled else None

    def _resolve_message_dispatcher(
        self,
        *,
        user_id: str,
        session_id: str | None,
    ) -> tuple[object | None, ChannelMessageDispatchOutcome | None]:
        try:
            return self._message_dispatcher or require_user_message_dispatcher(), None
        except RuntimeError as exc:
            return None, ChannelMessageDispatchOutcome(
                success=False,
                user_id=user_id,
                session_id=session_id,
                turn_id=None,
                message_id=None,
                error_code=MESSAGE_DISPATCHER_NOT_INITIALIZED,
                error_message=str(exc),
                queue_size=None,
            )


def _channel_dispatch_outcome(outcome: object) -> ChannelMessageDispatchOutcome:
    return ChannelMessageDispatchOutcome(
        success=outcome.success,
        user_id=outcome.user_id,
        session_id=outcome.session_id,
        turn_id=outcome.turn_id,
        message_id=outcome.message_id,
        error_code=outcome.error_code,
        error_message=outcome.error_message,
        queue_size=outcome.queue_size,
    )


def _invalid_inbound_metadata(message: str) -> ChannelInboundRejectedError:
    return ChannelInboundRejectedError(
        ChannelInboundRejectionReason.INVALID_METADATA,
        message,
    )


def _resolve_client_turn_id(
    *,
    source: str,
    client_turn_id: str | None,
    metadata: dict[str, object] | None,
) -> str | None:
    """Return an explicit or safely derived id for one external message."""

    if client_turn_id is not None:
        return client_turn_id
    if not isinstance(metadata, dict):
        return None

    channel = _stable_external_identifier(source)
    external_chat_id = _stable_external_identifier(metadata.get("external_chat_id"))
    external_message_id = _stable_external_identifier(
        metadata.get("external_message_id")
    )
    if channel is None or external_chat_id is None or external_message_id is None:
        return None

    identity = {
        "account_id": _stable_external_identifier(metadata.get("account_id")),
        "external_chat_id": external_chat_id,
        "external_message_id": external_message_id,
        "source": channel,
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{_EXTERNAL_TURN_PREFIX}{digest}"


def _stable_external_identifier(value: object) -> str | None:
    """Normalize scalar transport ids without accepting ambiguous values."""

    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    normalized = str(value).strip()
    return normalized or None


def _control_command_outcome(
    *,
    user_id: str,
    session_id: str | None,
    ack_message: str | None,
) -> ChannelMessageDispatchOutcome:
    """Build a dispatch outcome for a control / session command that was
    handled in the dispatcher (no LLM dispatch occurred).

    ``success`` is always True at the dispatch-layer (the message was
    accepted; we DID something useful with it). The user-facing result
    (approved / denied / not-found / session reset) is conveyed via
    ``error_message`` (carrying ``ack_message`` so the channel plugin can
    surface it); ``error_code`` left None. ``turn_id`` and ``message_id`` are
    None because no LLM turn / chat message was created."""
    return ChannelMessageDispatchOutcome(
        success=True,
        user_id=user_id,
        session_id=session_id,
        turn_id=None,
        message_id=None,
        error_code=None,
        error_message=ack_message,
        queue_size=0,
    )
