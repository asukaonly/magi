"""Session mapper — resolves external chat identifiers to Magi sessions."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Protocol

import aiosqlite
from magi_plugin_sdk.channels import ChannelInboundContext

from ..core.logger import get_logger
from ..identity import CANONICAL_LOCAL_USER, ExternalIdentity, IdentityResolver
from .contracts import ChannelSessionMapping
from .ingress_boundary import ChannelIngressBoundary

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
    """Maps (channel_type, external_chat_id) ↔ Magi session_id.

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
        db_path: str,
        session_provisioner: ChannelChatSessionProvisioner,
        ingress_boundary: ChannelIngressBoundary,
        identity_resolver: IdentityResolver | None = None,
    ) -> None:
        self._db_path = str(Path(db_path).expanduser())
        self._session_provisioner = session_provisioner
        self._ingress_boundary = ingress_boundary
        self._identity_resolver = identity_resolver
        self._initialized = False
        self._resolve_lock = asyncio.Lock()

    async def initialize(self) -> None:
        # Schema is alembic-managed (magi.db.migrations.channels).
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
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
    ) -> ChannelSessionMapping:
        """Look up existing mapping; if none, create a new Magi session."""
        async with self._ingress_boundary.operation(inbound_context):
            async with self._resolve_lock:
                existing = await self.lookup(channel_type, external_chat_id)
                if existing is not None:
                    available = (
                        await self._session_provisioner.is_channel_session_available(
                            magi_user_id=existing.magi_user_id,
                            session_id=existing.magi_session_id,
                        )
                    )
                    if available:
                        return await self._touch_existing_mapping(existing)
                    await self.delete_mapping(channel_type, external_chat_id)

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
                )
                await self._insert(mapping)
                self._log_mapping_created(mapping)
                return mapping

    async def _touch_existing_mapping(
        self,
        existing: ChannelSessionMapping,
    ) -> ChannelSessionMapping:
        now_ms = int(time.time() * 1000)
        await self._touch(existing.channel_type, existing.external_chat_id, now_ms)
        return ChannelSessionMapping(
            channel_type=existing.channel_type,
            external_chat_id=existing.external_chat_id,
            magi_session_id=existing.magi_session_id,
            magi_user_id=existing.magi_user_id,
            is_group=existing.is_group,
            created_at_ms=existing.created_at_ms,
            last_active_at_ms=now_ms,
            metadata_json=existing.metadata_json,
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
        )

    def _log_mapping_created(self, mapping: ChannelSessionMapping) -> None:
        logger.info(
            "Channel session created",
            channel_type=mapping.channel_type,
            external_chat_id=mapping.external_chat_id,
            session_id=mapping.magi_session_id,
        )

    async def lookup(
        self,
        channel_type: str,
        external_chat_id: str,
    ) -> ChannelSessionMapping | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM channel_session_mappings WHERE channel_type = ? AND external_chat_id = ?",
                (channel_type, external_chat_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._row_to_mapping(row)

    async def list_all(self) -> list[ChannelSessionMapping]:
        """Return every (channel, chat) → session mapping known to
        the host. Used by the channels-bindings API to render the
        full list of connected accounts (and their per-binding
        auto-approve toggles)."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM channel_session_mappings "
                "ORDER BY last_active_at_ms DESC"
            )
            rows = await cursor.fetchall()
            return [self._row_to_mapping(row) for row in rows]

    async def lookup_by_session(
        self,
        magi_session_id: str,
    ) -> ChannelSessionMapping | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM channel_session_mappings WHERE magi_session_id = ?",
                (magi_session_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._row_to_mapping(row)

    async def delete_mapping(
        self,
        channel_type: str,
        external_chat_id: str,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM channel_session_mappings WHERE channel_type = ? AND external_chat_id = ?",
                (channel_type, external_chat_id),
            )
            await db.commit()

    async def clear_conversation_state(self) -> dict[str, int]:
        """Remove channel data that can retain or recreate cleared conversations."""

        table_names = (
            "delivery_receipts",
            "outreach_outbox",
            "outreach_delivery_log",
            "channel_notification_cursors",
            "channel_session_mappings",
        )
        async with self._resolve_lock:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    counts: dict[str, int] = {}
                    for table_name in table_names:
                        cursor = await db.execute(f"DELETE FROM {table_name}")
                        counts[table_name] = int(cursor.rowcount or 0)
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
        return counts

    # -- notification cursor --------------------------------------------------

    async def get_notification_cursor(
        self,
        channel_type: str,
        external_chat_id: str,
    ) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT last_notification_id FROM channel_notification_cursors WHERE channel_type = ? AND external_chat_id = ?",
                (channel_type, external_chat_id),
            )
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def update_notification_cursor(
        self,
        channel_type: str,
        external_chat_id: str,
        notification_id: int,
    ) -> None:
        now_ms = int(time.time() * 1000)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO channel_notification_cursors
                       (channel_type, external_chat_id, last_notification_id, updated_at_ms)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(channel_type, external_chat_id)
                   DO UPDATE SET last_notification_id = excluded.last_notification_id,
                                 updated_at_ms = excluded.updated_at_ms""",
                (channel_type, external_chat_id, notification_id, now_ms),
            )
            await db.commit()

    async def get_relay_cursor(self, state_key: str) -> int:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT value_integer FROM channel_relay_state WHERE state_key = ?",
                (state_key,),
            )
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def update_relay_cursor(self, state_key: str, notification_id: int) -> None:
        now_ms = int(time.time() * 1000)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO channel_relay_state (state_key, value_integer, updated_at_ms)
                   VALUES (?, ?, ?)
                   ON CONFLICT(state_key)
                   DO UPDATE SET value_integer = excluded.value_integer,
                                 updated_at_ms = excluded.updated_at_ms""",
                (state_key, int(notification_id), now_ms),
            )
            await db.commit()

    # -- internals ------------------------------------------------------------

    async def _insert(self, mapping: ChannelSessionMapping) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT INTO channel_session_mappings
                       (channel_type, external_chat_id, magi_session_id, magi_user_id,
                        is_group, created_at_ms, last_active_at_ms, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mapping.channel_type,
                    mapping.external_chat_id,
                    mapping.magi_session_id,
                    mapping.magi_user_id,
                    1 if mapping.is_group else 0,
                    mapping.created_at_ms,
                    mapping.last_active_at_ms,
                    mapping.metadata_json,
                ),
            )
            await db.commit()

    async def _touch(self, channel_type: str, external_chat_id: str, now_ms: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE channel_session_mappings SET last_active_at_ms = ? WHERE channel_type = ? AND external_chat_id = ?",
                (now_ms, channel_type, external_chat_id),
            )
            await db.commit()

    @staticmethod
    def _row_to_mapping(row: aiosqlite.Row) -> ChannelSessionMapping:
        return ChannelSessionMapping(
            channel_type=row["channel_type"],
            external_chat_id=row["external_chat_id"],
            magi_session_id=row["magi_session_id"],
            magi_user_id=row["magi_user_id"],
            is_group=bool(row["is_group"]),
            created_at_ms=int(row["created_at_ms"]),
            last_active_at_ms=int(row["last_active_at_ms"]),
            metadata_json=row["metadata_json"],
        )
