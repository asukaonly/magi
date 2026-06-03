"""SQLite store for ``user_identity_bindings`` rows.

Records every ``(channel_type, external_user_id) -> MagiUserID``
mapping the resolver has seen. Single-user mode (the current
default) writes every binding with ``magi_user_id = CANONICAL_LOCAL_USER``;
the table is kept anyway because:

  1. It's the forensic record of which external accounts have ever
     reached this instance — useful for the "connected accounts"
     UI when multi-user lands.
  2. Switching to ``BindingTableResolver`` (multi-user) reads the
     same rows; no schema migration needed at that point.

Schema is alembic-managed (``magi.db.migrations.identity``). This
class only handles the runtime CRUD.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from ..core.logger import get_logger
from .types import ExternalIdentity, MagiUserID

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IdentityBinding:
    """One row of ``user_identity_bindings``."""

    channel_type: str
    external_user_id: str
    magi_user_id: MagiUserID
    created_at_ms: int
    last_seen_at_ms: int


class IdentityBindingsStore:
    """Async SQLite CRUD for ``user_identity_bindings``.

    Mirrors the shape of ``ChannelSessionMapper`` / ``DeliveryReceiptsStore``:
    one connection per call (aiosqlite handles this efficiently for
    write-light workloads), schema is initialized via alembic at
    process startup, and ``initialize()`` only verifies the parent
    directory exists.
    """

    def __init__(self, *, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())
        self._initialized = False

    async def initialize(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    async def lookup(
        self,
        external: ExternalIdentity,
    ) -> IdentityBinding | None:
        """Return the existing binding for ``external``, or None."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT channel_type, external_user_id, magi_user_id,
                       created_at_ms, last_seen_at_ms
                FROM user_identity_bindings
                WHERE channel_type = ? AND external_user_id = ?
                """,
                (external.channel_type, external.external_user_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return _row_to_binding(row)

    async def bind(
        self,
        external: ExternalIdentity,
        magi_user_id: MagiUserID,
    ) -> IdentityBinding:
        """Insert or update the binding. Updates ``last_seen_at_ms``
        even when the row exists; the ``UNIQUE(channel_type,
        external_user_id)`` constraint prevents duplicates.

        If a binding already exists with a DIFFERENT ``magi_user_id``,
        we honor the existing one — re-binding a user is an explicit
        operation that goes through a separate API (not yet
        implemented; see ``docs/identity-architecture.md`` §11).
        Until then, the first binding wins.
        """
        now_ms = int(time.time() * 1000)
        async with aiosqlite.connect(self._db_path) as db:
            # Try insert first; if the row exists, update last_seen and
            # return the existing binding regardless of the requested
            # magi_user_id. This makes ``bind`` idempotent in single-user
            # mode (every call uses CANONICAL_LOCAL_USER, the row never
            # needs to change).
            try:
                await db.execute(
                    """
                    INSERT INTO user_identity_bindings
                        (channel_type, external_user_id, magi_user_id,
                         created_at_ms, last_seen_at_ms)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        external.channel_type,
                        external.external_user_id,
                        str(magi_user_id),
                        now_ms,
                        now_ms,
                    ),
                )
                await db.commit()
                return IdentityBinding(
                    channel_type=external.channel_type,
                    external_user_id=external.external_user_id,
                    magi_user_id=magi_user_id,
                    created_at_ms=now_ms,
                    last_seen_at_ms=now_ms,
                )
            except aiosqlite.IntegrityError:
                # Existing row — touch last_seen and return the canonical
                # binding from the database.
                await db.execute(
                    """
                    UPDATE user_identity_bindings
                    SET last_seen_at_ms = ?
                    WHERE channel_type = ? AND external_user_id = ?
                    """,
                    (now_ms, external.channel_type, external.external_user_id),
                )
                await db.commit()
                existing = await self.lookup(external)
                assert existing is not None, "row vanished between insert and lookup"
                return existing

    async def lookup_externals(
        self,
        magi_user_id: MagiUserID,
    ) -> list[ExternalIdentity]:
        """Return all external identities currently bound to ``magi_user_id``.

        Used by the future "connected accounts" UI. In single-user mode
        this returns the (potentially large) list of every external
        account that has ever written to the instance.
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT channel_type, external_user_id
                FROM user_identity_bindings
                WHERE magi_user_id = ?
                ORDER BY last_seen_at_ms DESC
                """,
                (str(magi_user_id),),
            )
            rows = await cursor.fetchall()
            return [
                ExternalIdentity(
                    channel_type=row["channel_type"],
                    external_user_id=row["external_user_id"],
                )
                for row in rows
            ]


def _row_to_binding(row: aiosqlite.Row) -> IdentityBinding:
    return IdentityBinding(
        channel_type=row["channel_type"],
        external_user_id=row["external_user_id"],
        magi_user_id=MagiUserID(row["magi_user_id"]),
        created_at_ms=int(row["created_at_ms"]),
        last_seen_at_ms=int(row["last_seen_at_ms"]),
    )


__all__ = ["IdentityBinding", "IdentityBindingsStore"]
