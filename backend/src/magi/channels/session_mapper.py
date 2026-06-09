"""Session mapper — resolves external chat identifiers to Magi sessions."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import aiosqlite

from ..chat import ChatSessionRecord, ChatStore
from ..core.logger import get_logger
from ..identity import CANONICAL_LOCAL_USER, ExternalIdentity, IdentityResolver
from .contracts import ChannelSessionMapping

logger = get_logger(__name__)


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
        chat_store: ChatStore,
        identity_resolver: IdentityResolver | None = None,
    ) -> None:
        self._db_path = str(Path(db_path).expanduser())
        self._chat_store = chat_store
        self._identity_resolver = identity_resolver
        self._initialized = False

    async def initialize(self) -> None:
        # Schema is alembic-managed (magi.db.migrations.channels).
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    async def resolve_or_create(
        self,
        *,
        channel_type: str,
        external_chat_id: str,
        external_user_id: str,
        is_group: bool = False,
        display_name: str | None = None,
    ) -> ChannelSessionMapping:
        """Look up existing mapping; if none, create a new Magi session."""
        existing = await self.lookup(channel_type, external_chat_id)
        if existing is not None:
            now_ms = int(time.time() * 1000)
            await self._touch(channel_type, external_chat_id, now_ms)
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

        # Phase H+2 identity layer: external_user_id flows through the
        # IdentityResolver so the magi_user_id column stores the
        # canonical MagiUserID, never the raw external id. Legacy
        # callers without a resolver still get the canonical default
        # (single-user assumption); the old f"channel_{type}_{ext}"
        # synthesis is gone.
        if self._identity_resolver is not None:
            magi_user_id = str(
                await self._identity_resolver.resolve(
                    ExternalIdentity(
                        channel_type=channel_type,
                        external_user_id=external_user_id,
                    )
                )
            )
        else:
            magi_user_id = str(CANONICAL_LOCAL_USER)
        session_id = f"chsess_{uuid.uuid4().hex[:12]}"
        now_ms = int(time.time() * 1000)
        title = display_name or f"{channel_type.capitalize()}: {external_chat_id}"

        await self._chat_store.upsert_session(
            ChatSessionRecord(
                session_id=session_id,
                user_id=magi_user_id,
                title=title,
                title_overridden=False,
                summary="",
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
                last_message_at_ms=None,
                last_user_message_at_ms=None,
                last_message_preview="",
                last_user_message_preview="",
                message_count=0,
                archived_at_ms=None,
                deleted_at_ms=None,
                workspace_path=None,
                history_version=0,
            )
        )

        meta = {
            "external_user_id": external_user_id,
            "display_name": display_name,
        }

        mapping = ChannelSessionMapping(
            channel_type=channel_type,
            external_chat_id=external_chat_id,
            magi_session_id=session_id,
            magi_user_id=magi_user_id,
            is_group=is_group,
            created_at_ms=now_ms,
            last_active_at_ms=now_ms,
            metadata_json=json.dumps(meta, ensure_ascii=False),
        )
        await self._insert(mapping)
        logger.info(
            "Channel session created",
            channel_type=channel_type,
            external_chat_id=external_chat_id,
            session_id=session_id,
        )
        return mapping

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
