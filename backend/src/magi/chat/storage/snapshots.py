"""Atomic native logical transfer of every chat-owned lifecycle collection."""

from ..storage_snapshot import ChatStorageSnapshot
from ...db.logical_transfer import snapshot_digest
from .relational import AsyncChatConnection, ChatDatabase

# Ordered parent-first, followed by cleanup fences and exact read revisions.
# Names come from the checked-in transfer contract, never from archive input.
COLLECTIONS = tuple(name for name in ChatStorageSnapshot.model_fields if name != "version")
TABLES = tuple("chat_" + name for name in COLLECTIONS)


class RelationalChatStateTransfer:
    """Caller holds the offline worker lease; import never dispatches queued work."""

    def __init__(self, database: ChatDatabase) -> None:
        self.database = database

    @staticmethod
    async def _export(connection: AsyncChatConnection) -> ChatStorageSnapshot:
        values = {}
        for name, table in zip(COLLECTIONS, TABLES, strict=True):
            records = await connection.execute_fetchall(f"SELECT * FROM {table}")
            values[name] = [dict(row) for row in records]
        return ChatStorageSnapshot.model_validate(values)

    async def export_state(self) -> ChatStorageSnapshot:
        async with self.database.session() as connection:
            # Serialize with both native write and cleanup owners for one snapshot.
            await connection.begin_write()
            return await self._export(connection)

    async def import_state(self, snapshot: ChatStorageSnapshot, *, replace: bool = False) -> None:
        snapshot = ChatStorageSnapshot.model_validate(snapshot.model_dump(mode="json"))
        async with self.database.session() as connection:
            await connection.begin_write()
            if not replace and not (await self._export(connection)).is_empty():
                raise ValueError("Destination has data; explicit replacement is required")
            for table in reversed(TABLES):
                await connection.execute(f"DELETE FROM {table}")
            for name, table in zip(COLLECTIONS, TABLES, strict=True):
                if name == "cleared_message_scopes":
                    # Keep unavailable parents writable only inside this offline
                    # transaction, then restore their lifecycle before fences.
                    await connection.executemany(
                        "UPDATE chat_sessions SET archived_at_ms=?, deleted_at_ms=? WHERE session_id=?",
                        [(row.archived_at_ms, row.deleted_at_ms, row.session_id)
                         for row in snapshot.sessions if row.archived_at_ms is not None or row.deleted_at_ms is not None],
                    )
                # Native mutation triggers increment revisions while importing rows.
                # Restore the exact exported revision after all triggering tables.
                if name == "read_revisions":
                    await connection.execute("DELETE FROM chat_read_revisions")
                rows = getattr(snapshot, name)
                if name == "sessions":
                    rows = [row.model_copy(update={"archived_at_ms": None, "deleted_at_ms": None}) for row in rows]
                if not rows:
                    continue
                columns = tuple(type(rows[0]).model_fields)
                await connection.executemany(
                    f"INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    [tuple(getattr(row, column) for column in columns) for row in rows],
                )
            if snapshot_digest(await self._export(connection)) != snapshot_digest(snapshot):
                raise ValueError("Chat import did not preserve the complete logical state")
            await connection.commit()
