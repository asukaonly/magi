"""Transactions and row conversion for the MySQL event owner."""

from contextlib import asynccontextmanager
from hashlib import sha256
import json
from typing import AsyncIterator

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from magi.core.persistence_errors import PersistenceConflictError
from magi.db.mysql import MysqlDatabase
from .schema import state, events, embeddings
from ..event_mapping import event_record_from_mapping


def identity(*values: str) -> str:
    """Hash length-independent identities without delimiter collisions."""
    return sha256(
        json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def nullable_identity(value: str | None) -> str | None:
    return identity(value) if value is not None else None


def event_select():
    return select(
        events,
        embeddings.c.embedding_status,
        embeddings.c.embedding_profile_id,
        embeddings.c.embedding_chunk_count,
        embeddings.c.last_embedded_at,
    ).select_from(events.outerjoin(embeddings, events.c.event_key == embeddings.c.event_key))


def record(row, *, include_metadata: bool = True):
    values = dict(row)
    if not include_metadata:
        values["metadata_json"] = None
    return event_record_from_mapping(values)


class MysqlEventConnection:
    def __init__(self, database: MysqlDatabase, *, center_id: str) -> None:
        if not center_id.strip():
            raise ValueError("Memory storage requires a center identity")
        self._database = database
        self._center_id = center_id

    async def initialize(self) -> None:
        """Validate migrated schema and bind a previously empty owner."""
        async with self._database.transaction() as connection:
            owner = (
                (
                    await connection.execute(
                        select(state).where(state.c.singleton_id == 1).with_for_update()
                    )
                )
                .mappings()
                .one()
            )
            if owner["center_id"] is None:
                await connection.execute(
                    update(state).where(state.c.singleton_id == 1).values(center_id=self._center_id)
                )
            elif owner["center_id"] != self._center_id:
                raise PersistenceConflictError("Memory storage belongs to another center")
            await connection.execute(event_select().limit(0))

    @asynccontextmanager
    async def _transaction(self, *, write: bool = False) -> AsyncIterator[AsyncConnection]:
        async with self._database.transaction() as connection:
            query = select(state.c.center_id).where(state.c.singleton_id == 1)
            query = query.with_for_update(read=not write)
            owner = (await connection.execute(query)).scalar_one()
            if owner != self._center_id:
                raise PersistenceConflictError("Memory storage owner is not initialized")
            yield connection
