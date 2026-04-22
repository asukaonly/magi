"""Inbound message dispatch adapter for channel plugins."""

from __future__ import annotations

from magi_plugin_sdk.channels import (
    ChannelMessageDispatcherProtocol,
    ChannelMessageDispatchOutcome,
)

from ..api.services.message_dispatch_service import dispatch_user_message


class ChannelMessageDispatcher(ChannelMessageDispatcherProtocol):
    """Adapt the backend message dispatch service to the channel SDK contract."""

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
            error_code=outcome.error_code,
            error_message=outcome.error_message,
            queue_size=outcome.queue_size,
        )