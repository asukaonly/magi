from __future__ import annotations

from magi.channels import Channel as BackendChannel
from magi.channels import ChannelConfig as BackendChannelConfig
from magi.channels import ChannelAttachmentStoreProtocol as BackendChannelAttachmentStoreProtocol
from magi.channels import ChannelMessageDispatcherProtocol as BackendChannelMessageDispatcherProtocol
from magi.channels import ChannelMessageDispatchOutcome as BackendChannelMessageDispatchOutcome
from magi.channels import ChannelSessionMapperProtocol as BackendChannelSessionMapperProtocol
from magi.channels import ChannelSessionMapping as BackendChannelSessionMapping
from magi.channels import ChannelTarget as BackendChannelTarget
from magi.channels import InboundMessage as BackendInboundMessage
from magi.channels import OutboundContent as BackendOutboundContent
from magi.channels.contracts import ChannelMessageDispatcherProtocol as BackendChannelContractsMessageDispatcherProtocol
from magi.channels.contracts import ChannelMessageDispatchOutcome as BackendChannelContractsMessageDispatchOutcome
from magi_plugin_sdk.channels import Channel as SdkChannel
from magi_plugin_sdk.channels import ChannelConfig as SdkChannelConfig
from magi_plugin_sdk.channels import ChannelAttachmentStoreProtocol as SdkChannelAttachmentStoreProtocol
from magi_plugin_sdk.channels import ChannelMessageDispatcherProtocol as SdkChannelMessageDispatcherProtocol
from magi_plugin_sdk.channels import ChannelMessageDispatchOutcome as SdkChannelMessageDispatchOutcome
from magi_plugin_sdk.channels import ChannelSessionMapperProtocol as SdkChannelSessionMapperProtocol
from magi_plugin_sdk.channels import ChannelSessionMapping as SdkChannelSessionMapping
from magi_plugin_sdk.channels import ChannelTarget as SdkChannelTarget
from magi_plugin_sdk.channels import InboundMessage as SdkInboundMessage
from magi_plugin_sdk.channels import OutboundContent as SdkOutboundContent


class StubChannelSessionMapper:
    async def resolve_or_create(
        self,
        *,
        channel_type: str,
        external_chat_id: str,
        external_user_id: str,
        is_group: bool = False,
        display_name: str | None = None,
    ) -> SdkChannelSessionMapping:
        return SdkChannelSessionMapping(
            channel_type=channel_type,
            external_chat_id=external_chat_id,
            magi_session_id="chsess_test",
            magi_user_id=f"channel_{channel_type}_{external_user_id}",
            is_group=is_group,
            metadata_json=display_name or "{}",
        )

    async def lookup(
        self,
        channel_type: str,
        external_chat_id: str,
    ) -> SdkChannelSessionMapping | None:
        return None

    async def lookup_by_session(self, magi_session_id: str) -> SdkChannelSessionMapping | None:
        _ = magi_session_id
        return None

    async def delete_mapping(self, channel_type: str, external_chat_id: str) -> None:
        _ = channel_type, external_chat_id

    async def get_notification_cursor(self, channel_type: str, external_chat_id: str) -> int:
        _ = channel_type, external_chat_id
        return 0

    async def update_notification_cursor(
        self,
        channel_type: str,
        external_chat_id: str,
        notification_id: int,
    ) -> None:
        _ = channel_type, external_chat_id, notification_id


class StubChannelMessageDispatcher:
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
    ) -> SdkChannelMessageDispatchOutcome:
        _ = (
            source,
            user_id,
            message,
            session_id,
            attachments,
            reply_to_message_id,
            workspace_path,
            client_turn_id,
            metadata,
            runtime_namespace,
        )
        return SdkChannelMessageDispatchOutcome(success=True, user_id=user_id)


class StubChannelAttachmentStore:
    async def store_attachment(
        self,
        *,
        session_id: str,
        turn_id: str,
        kind: str,
        original_name: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, object]:
        _ = session_id, turn_id, kind, original_name, content, mime_type
        return {"attachment_id": "att_test", "kind": "file"}


def test_backend_channel_contracts_reexport_sdk_symbols() -> None:
    assert BackendChannel is SdkChannel
    assert BackendChannelConfig is SdkChannelConfig
    assert BackendChannelAttachmentStoreProtocol is SdkChannelAttachmentStoreProtocol
    assert BackendChannelMessageDispatcherProtocol is SdkChannelMessageDispatcherProtocol
    assert BackendChannelMessageDispatchOutcome is SdkChannelMessageDispatchOutcome
    assert BackendChannelContractsMessageDispatcherProtocol is SdkChannelMessageDispatcherProtocol
    assert BackendChannelContractsMessageDispatchOutcome is SdkChannelMessageDispatchOutcome
    assert BackendChannelSessionMapperProtocol is SdkChannelSessionMapperProtocol
    assert BackendChannelSessionMapping is SdkChannelSessionMapping
    assert BackendChannelTarget is SdkChannelTarget
    assert BackendInboundMessage is SdkInboundMessage
    assert BackendOutboundContent is SdkOutboundContent


def test_channel_session_mapper_protocol_supports_structural_typing() -> None:
    assert isinstance(StubChannelSessionMapper(), SdkChannelSessionMapperProtocol)


def test_channel_message_dispatcher_protocol_supports_structural_typing() -> None:
    assert isinstance(StubChannelMessageDispatcher(), SdkChannelMessageDispatcherProtocol)


def test_channel_attachment_store_protocol_supports_structural_typing() -> None:
    assert isinstance(StubChannelAttachmentStore(), SdkChannelAttachmentStoreProtocol)