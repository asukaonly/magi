from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from magi.channels.attachment_store import GuardedChannelAttachmentStore
from magi.channels.control_commands import HostControlPort
from magi.channels.dispatcher import ChannelMessageDispatcher
from magi.channels.ingress_boundary import ChannelIngressBoundary
from magi.channels.session_mapper import ChannelSessionMapper
from magi.events.runtime_queue import SQLiteRuntimeCommandQueue
from magi_plugin_sdk.channels import (
    ChannelInboundContext,
    ChannelInboundRejectedError,
    ChannelInboundRejectionReason,
)


class _SessionProvisioner:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.available: set[str] = set()

    async def create_channel_session(self, **_kwargs: object) -> str:
        session_id = f"session-{len(self.created) + 1}"
        self.created.append(session_id)
        self.available.add(session_id)
        return session_id

    async def is_channel_session_available(
        self,
        *,
        magi_user_id: str,
        session_id: str,
    ) -> bool:
        del magi_user_id
        return session_id in self.available


class _RecordingAttachmentStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def store_attachment(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(dict(kwargs))
        return {"attachment_id": "attachment-1"}


class _RecordingDispatch:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def __call__(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            success=True,
            user_id=kwargs["user_id"],
            session_id=kwargs["session_id"],
            turn_id=kwargs["client_turn_id"],
            message_id="message-1",
            error_code=None,
            error_message=None,
            queue_size=0,
        )


@pytest.mark.asyncio
async def test_stale_context_cannot_create_mapping_attachment_or_message(
    runtime_paths_with_schema,
) -> None:
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path)
    )
    await queue.start()
    boundary = ChannelIngressBoundary(runtime_command_queue=queue)
    context = await boundary.capture(provider_occurred_at_ms=1)
    provisioner = _SessionProvisioner()
    mapper = ChannelSessionMapper(
        db_path=str(runtime_paths_with_schema.channels_db_path),
        session_provisioner=provisioner,
        ingress_boundary=boundary,
    )
    await mapper.initialize()
    raw_attachment_store = _RecordingAttachmentStore()
    attachment_store = GuardedChannelAttachmentStore(
        delegate=raw_attachment_store,
        ingress_boundary=boundary,
    )
    raw_dispatch = _RecordingDispatch()
    dispatcher = ChannelMessageDispatcher(
        ingress_boundary=boundary,
        message_dispatcher=raw_dispatch,
    )
    control_port = HostControlPort(ingress_boundary=boundary)

    try:
        async with queue.user_message_global_clear_boundary():
            await queue.advance_user_message_generation_and_purge()

        for operation in (
            mapper.resolve_or_create(
                inbound_context=context,
                channel_type="telegram",
                external_chat_id="chat-1",
                external_user_id="user-1",
            ),
            attachment_store.store_attachment(
                inbound_context=context,
                session_id="session-1",
                turn_id="turn-1",
                kind="file",
                original_name="private.txt",
                content=b"private",
                mime_type="text/plain",
            ),
            dispatcher.dispatch_user_message(
                inbound_context=context,
                source="telegram",
                user_id="local_user",
                message="private",
                session_id="session-1",
                metadata={
                    "external_chat_id": "chat-1",
                    "external_message_id": "message-1",
                },
            ),
            control_port.handle_command(
                inbound_context=context,
                message="/help",
                session_id="session-1",
                channel_type="telegram",
                external_chat_id="chat-1",
                external_user_id="user-1",
            ),
        ):
            with pytest.raises(ChannelInboundRejectedError) as exc_info:
                await operation
            assert (
                exc_info.value.reason
                is ChannelInboundRejectionReason.CLEARED_MESSAGE
            )

        assert provisioner.created == []
        assert raw_attachment_store.calls == []
        assert raw_dispatch.calls == []
        assert await mapper.lookup("telegram", "chat-1") is None
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_clear_waits_for_mapping_then_removes_it_without_empty_session_tail(
    runtime_paths_with_schema,
) -> None:
    class _BlockingProvisioner(_SessionProvisioner):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def create_channel_session(self, **kwargs: object) -> str:
            self.entered.set()
            await self.release.wait()
            return await super().create_channel_session(**kwargs)

    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path)
    )
    await queue.start()
    boundary = ChannelIngressBoundary(runtime_command_queue=queue)
    context = await boundary.capture(provider_occurred_at_ms=1)
    provisioner = _BlockingProvisioner()
    mapper = ChannelSessionMapper(
        db_path=str(runtime_paths_with_schema.channels_db_path),
        session_provisioner=provisioner,
        ingress_boundary=boundary,
    )
    await mapper.initialize()
    cleared = asyncio.Event()

    async def resolve() -> None:
        await mapper.resolve_or_create(
            inbound_context=context,
            channel_type="weixin",
            external_chat_id="chat-1",
            external_user_id="user-1",
        )

    async def clear() -> None:
        await provisioner.entered.wait()
        async with queue.user_message_global_clear_boundary():
            await queue.advance_user_message_generation_and_purge()
            await mapper.clear_conversation_state()
            cleared.set()

    resolve_task = asyncio.create_task(resolve())
    clear_task = asyncio.create_task(clear())
    try:
        await provisioner.entered.wait()
        await asyncio.sleep(0)
        assert not cleared.is_set()
        provisioner.release.set()
        await asyncio.wait_for(asyncio.gather(resolve_task, clear_task), timeout=1)
        assert cleared.is_set()
        assert await mapper.lookup("weixin", "chat-1") is None
    finally:
        provisioner.release.set()
        await asyncio.gather(resolve_task, clear_task, return_exceptions=True)
        await queue.stop()


@pytest.mark.asyncio
async def test_host_boundary_rejects_forged_or_missing_context(
    runtime_paths_with_schema,
) -> None:
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path)
    )
    await queue.start()
    boundary = ChannelIngressBoundary(runtime_command_queue=queue)
    try:
        with pytest.raises(ChannelInboundRejectedError) as missing_context:
            async with boundary.operation(None):  # type: ignore[arg-type]
                pass
        assert (
            missing_context.value.reason
            is ChannelInboundRejectionReason.INVALID_METADATA
        )

        forged = ChannelInboundContext(
            provider_occurred_at_ms=1,
            clear_generation=-1,
        )
        with pytest.raises(ChannelInboundRejectedError) as forged_context:
            async with boundary.operation(forged):
                pass
        assert (
            forged_context.value.reason
            is ChannelInboundRejectionReason.INVALID_METADATA
        )
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_dispatcher_persists_host_controlled_clear_metadata(
    runtime_paths_with_schema,
) -> None:
    queue = SQLiteRuntimeCommandQueue(
        db_path=str(runtime_paths_with_schema.message_queue_db_path)
    )
    await queue.start()
    boundary = ChannelIngressBoundary(runtime_command_queue=queue)
    context = await boundary.capture(provider_occurred_at_ms=1_700_000_000_123)
    raw_dispatch = _RecordingDispatch()
    dispatcher = ChannelMessageDispatcher(
        ingress_boundary=boundary,
        message_dispatcher=raw_dispatch,
    )
    try:
        await dispatcher.dispatch_user_message(
            inbound_context=context,
            source="telegram",
            user_id="local_user",
            message="hello",
            session_id="session-1",
            metadata={
                "provider_occurred_at_ms": 9,
                "channel_clear_generation": 999,
                "external_chat_id": "chat-1",
                "external_message_id": "message-1",
            },
        )
        metadata = raw_dispatch.calls[0]["metadata"]
        assert isinstance(metadata, dict)
        assert metadata["provider_occurred_at_ms"] == context.provider_occurred_at_ms
        assert metadata["channel_clear_generation"] == context.clear_generation
    finally:
        await queue.stop()
