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

from ..core.runtime_bindings import require_user_message_dispatcher
from ..control.permission.slash_commands import try_handle_control_command
from .session_commands import try_handle_session_command


MESSAGE_DISPATCHER_NOT_INITIALIZED = "MESSAGE_DISPATCHER_NOT_INITIALIZED"


class ChannelMessageDispatcher(ChannelMessageDispatcherProtocol):
    """Adapt the backend message dispatch service to the channel SDK contract."""

    def __init__(
        self,
        *,
        permission_registry: object | None = None,
        interaction_broker: object | None = None,
        session_mapper: object | None = None,
        message_dispatcher: object | None = None,
    ) -> None:
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
                    ack_message=control_outcome.ack_message,
                )

        # New-session command short-circuit (channels layer): reset the
        # session→channel binding so the NEXT message starts a fresh session.
        # No LLM turn; the ack is surfaced to the user via the channel.
        if self._session_mapper is not None:
            session_outcome = await try_handle_session_command(
                message=message,
                session_id=session_id,
                session_mapper=self._session_mapper,
            )
            if session_outcome.handled:
                return _control_command_outcome(
                    user_id=user_id,
                    session_id=session_id,
                    ack_message=session_outcome.ack_message,
                )

        try:
            dispatch_user_message = self._message_dispatcher or require_user_message_dispatcher()
        except RuntimeError as exc:
            return ChannelMessageDispatchOutcome(
                success=False,
                user_id=user_id,
                session_id=session_id,
                turn_id=None,
                message_id=None,
                error_code=MESSAGE_DISPATCHER_NOT_INITIALIZED,
                error_message=str(exc),
                queue_size=None,
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
