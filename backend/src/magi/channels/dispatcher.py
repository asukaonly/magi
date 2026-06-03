"""Inbound message dispatch adapter for channel plugins.

Phase H+2: control-command short-circuit. If the inbound message
parses as ``/approve <short_id>`` or ``/deny <short_id>``, the
dispatcher resolves the pending permission via the broker and
returns success WITHOUT going through ``dispatch_user_message`` —
the LLM never sees the slash command. Falls through to normal
dispatch for any other message.
"""
from __future__ import annotations

from magi_plugin_sdk.channels import (
    ChannelMessageDispatcherProtocol,
    ChannelMessageDispatchOutcome,
)

from ..api.services.message_dispatch_service import dispatch_user_message
from ..control.permission.slash_commands import (
    ControlCommandOutcome,
    try_handle_control_command,
)


class ChannelMessageDispatcher(ChannelMessageDispatcherProtocol):
    """Adapt the backend message dispatch service to the channel SDK contract."""

    def __init__(
        self,
        *,
        permission_registry: object | None = None,
        interaction_broker: object | None = None,
    ) -> None:
        # Optional Phase H+2 wiring — when both are provided, inbound
        # messages are checked for /approve|/deny slash commands before
        # being dispatched to the LLM. When None (legacy / tests that
        # don't care about control commands), the slash-command path
        # is disabled and every message dispatches normally.
        self._permission_registry = permission_registry
        self._interaction_broker = interaction_broker

    async def dispatch_user_message(
        self,
        *,
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
        # Phase H+2: try the slash-command short-circuit first.
        if (
            self._permission_registry is not None
            and self._interaction_broker is not None
        ):
            control_outcome = await try_handle_control_command(
                message=message,
                session_id=session_id,
                registry=self._permission_registry,  # type: ignore[arg-type]
                broker=self._interaction_broker,  # type: ignore[arg-type]
            )
            if control_outcome.handled:
                return _control_command_outcome(
                    user_id=user_id,
                    session_id=session_id,
                    control_outcome=control_outcome,
                )

        outcome = await dispatch_user_message(
            source=source,
            user_id=user_id,
            message=message,
            session_id=session_id,
            attachments=attachments,
            reply_to_message_id=reply_to_message_id,
            workspace_path=workspace_path,
            client_turn_id=client_turn_id,
            metadata=metadata,
            runtime_namespace=runtime_namespace,
        )
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


def _control_command_outcome(
    *,
    user_id: str,
    session_id: str | None,
    control_outcome: ControlCommandOutcome,
) -> ChannelMessageDispatchOutcome:
    """Build a dispatch outcome for a control command that was handled
    by the slash-command parser (no LLM dispatch occurred).

    ``success`` is always True at the dispatch-layer (the message was
    accepted; we DID something useful with it). Whether the underlying
    permission was approved / denied / not-found is conveyed via
    ``error_message`` (which carries ``ack_message`` so the channel
    plugin can surface it to the user); ``error_code`` left None.
    ``turn_id`` and ``message_id`` are None because no LLM turn / chat
    message was created."""
    return ChannelMessageDispatchOutcome(
        success=True,
        user_id=user_id,
        session_id=session_id,
        turn_id=None,
        message_id=None,
        error_code=None,
        error_message=control_outcome.ack_message,
        queue_size=0,
    )
