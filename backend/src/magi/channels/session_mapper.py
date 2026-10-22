"""Session mapper — resolves external chat identifiers to Magi sessions."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Protocol

from magi_plugin_sdk.channels import ChannelInboundContext

from ..core.logger import get_logger
from ..identity import CANONICAL_LOCAL_USER, ExternalIdentity, IdentityResolver
from .contracts import ChannelSessionMapping
from .ingress_boundary import ChannelIngressBoundary
from .ports import ChannelSessionRepository

logger = get_logger(__name__)


class ChannelChatSessionProvisioner(Protocol):
    """Creates chat-domain sessions for external channel conversations."""

    async def create_channel_session(
        self,
        *,
        channel_type: str,
        external_chat_id: str,
        magi_user_id: str,
        display_name: str | None,
        created_at_ms: int,
    ) -> str:
        ...

    async def is_channel_session_available(
        self,
        *,
        magi_user_id: str,
        session_id: str,
    ) -> bool:
        ...


class ChannelSessionMapper:
    """Maps (channel_type, external_chat_id, external_thread_id) ↔ Magi session_id.

    Ingress site #1 for identity canonicalization
    (``docs/identity-architecture.md`` §6.5). When ``resolver`` is
    supplied, ``resolve_or_create`` calls ``resolver.resolve()`` to
    canonicalize the external user identity into a ``MagiUserID``
    before stamping it onto ``magi_user_id``. Without a resolver
    (legacy callers / tests), the synthesized
    ``channel_{channel_type}_{external_user_id}`` value is replaced
    with ``CANONICAL_LOCAL_USER`` — the single-user assumption that
    already holds everywhere else in the codebase.
    """

    def __init__(
        self,
        *,
        repository: ChannelSessionRepository,
        session_provisioner: ChannelChatSessionProvisioner,
        ingress_boundary: ChannelIngressBoundary,
        identity_resolver: IdentityResolver | None = None,
    ) -> None:
        self._repository = repository
        self._session_provisioner = session_provisioner
        self._ingress_boundary = ingress_boundary
        self._identity_resolver = identity_resolver
        self._initialized = False
        self._resolve_lock = asyncio.Lock()

    async def initialize(self) -> None:
        await self._repository.initialize()
        self._initialized = True

    async def resolve_or_create(
        self,
        *,
        inbound_context: ChannelInboundContext,
        channel_type: str,
        external_chat_id: str,
        external_user_id: str,
        is_group: bool = False,
        display_name: str | None = None,
        external_thread_id: str | None = None,
    ) -> ChannelSessionMapping:
        """Look up existing mapping; if none, create a new Magi session."""
        if external_thread_id is not None and (
            not isinstance(external_thread_id, str) or not external_thread_id.strip()
        ):
            raise ValueError("External thread identifier must be a non-empty string")
        async with self._ingress_boundary.operation(
            inbound_context,
            expected_channel_type=channel_type,
        ):
            async with self._resolve_lock:
                existing = await self.lookup(channel_type, external_chat_id, external_thread_id=external_thread_id)
                if existing is not None:
                    available = (
                        await self._session_provisioner.is_channel_session_available(
                            magi_user_id=existing.magi_user_id,
                            session_id=existing.magi_session_id,
                        )
                    )
                    if available:
                        return await self._touch_existing_mapping(existing)
                    await self.delete_mapping(channel_type, external_chat_id, external_thread_id=external_thread_id)

                magi_user_id = await self._resolve_magi_user_id(
                    channel_type=channel_type,
                    external_user_id=external_user_id,
                )
                now_ms = int(time.time() * 1000)
                session_id = await self._session_provisioner.create_channel_session(
                    channel_type=channel_type,
                    external_chat_id=external_chat_id,
                    magi_user_id=magi_user_id,
                    display_name=display_name,
                    created_at_ms=now_ms,
                )

                mapping = self._build_new_mapping(
                    channel_type=channel_type,
                    external_chat_id=external_chat_id,
                    magi_user_id=magi_user_id,
                    session_id=session_id,
                    is_group=is_group,
                    display_name=display_name,
                    external_user_id=external_user_id,
                    now_ms=now_ms,
                    external_thread_id=external_thread_id,
                )
                await self._repository.insert(mapping)
                self._log_mapping_created(mapping)
                return mapping

    async def _touch_existing_mapping(
        self,
        existing: ChannelSessionMapping,
    ) -> ChannelSessionMapping:
        now_ms = int(time.time() * 1000)
        await self._repository.touch(existing.channel_type, existing.external_chat_id, now_ms, external_thread_id=existing.external_thread_id)
        return ChannelSessionMapping(
            channel_type=existing.channel_type,
            external_chat_id=existing.external_chat_id,
            magi_session_id=existing.magi_session_id,
            magi_user_id=existing.magi_user_id,
            is_group=existing.is_group,
            created_at_ms=existing.created_at_ms,
            last_active_at_ms=now_ms,
            metadata_json=existing.metadata_json,
            external_thread_id=existing.external_thread_id,
        )

    async def _resolve_magi_user_id(
        self,
        *,
        channel_type: str,
        external_user_id: str,
    ) -> str:
        if self._identity_resolver is None:
            return str(CANONICAL_LOCAL_USER)
        return str(
            await self._identity_resolver.resolve(
                ExternalIdentity(
                    channel_type=channel_type,
                    external_user_id=external_user_id,
                )
            )
        )

    def _build_new_mapping(
        self,
        *,
        channel_type: str,
        external_chat_id: str,
        magi_user_id: str,
        session_id: str,
        is_group: bool,
        display_name: str | None,
        external_user_id: str,
        now_ms: int,
        external_thread_id: str | None,
    ) -> ChannelSessionMapping:
        metadata = {
            "external_user_id": external_user_id,
            "display_name": display_name,
        }
        return ChannelSessionMapping(
            channel_type=channel_type,
            external_chat_id=external_chat_id,
            magi_session_id=session_id,
            magi_user_id=magi_user_id,
            is_group=is_group,
            created_at_ms=now_ms,
            last_active_at_ms=now_ms,
            metadata_json=json.dumps(metadata, ensure_ascii=False),
            external_thread_id=external_thread_id,
        )

    def _log_mapping_created(self, mapping: ChannelSessionMapping) -> None:
        logger.info(
            "Channel session created",
            channel_type=mapping.channel_type,
            external_chat_id=mapping.external_chat_id,
            session_id=mapping.magi_session_id,
        )

    async def lookup(self, channel_type: str, external_chat_id: str, *, external_thread_id: str | None = None) -> ChannelSessionMapping | None:
        return await self._repository.lookup(channel_type, external_chat_id, external_thread_id=external_thread_id)

    async def lookup_by_session(self, magi_session_id: str) -> ChannelSessionMapping | None:
        return await self._repository.lookup_by_session(magi_session_id)

    async def list_all(self) -> list[ChannelSessionMapping]:
        return await self._repository.list_all()

    async def delete_mapping(self, channel_type: str, external_chat_id: str, *, external_thread_id: str | None = None) -> None:
        await self._repository.delete_mapping(channel_type, external_chat_id, external_thread_id=external_thread_id)

    async def clear_conversation_state(self) -> dict[str, int]:
        async with self._resolve_lock:
            return await self._repository.clear_conversation_state()

    async def get_notification_cursor(self, channel_type: str, external_chat_id: str) -> int:
        return await self._repository.get_notification_cursor(channel_type, external_chat_id)

    async def update_notification_cursor(self, channel_type: str, external_chat_id: str, notification_id: int) -> None:
        await self._repository.update_notification_cursor(channel_type, external_chat_id, notification_id)

    async def get_relay_cursor(self, state_key: str) -> int:
        return await self._repository.get_relay_cursor(state_key)

    async def update_relay_cursor(self, state_key: str, notification_id: int) -> None:
        await self._repository.update_relay_cursor(state_key, notification_id)
