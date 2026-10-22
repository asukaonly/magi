"""Atomic SQLite logical state transfer for the complete L1 owner."""

from __future__ import annotations

from typing import Any

import aiosqlite

from magi.memory.hybrid_retrieval.fts_utils import tokenize_for_fts
from ..storage_snapshot import EventStorageSnapshot
from .connection import event_connection
from .snapshot_mapping import fact_row, fact_search_text, snapshot_fact

TABLES = {
    "facts": "fact_events",
    "sequences": "l1_session_sequences",
    "embeddings": "l1_event_embedding_state",
    "payloads": "l1_event_payload",
    "handoffs": "l1_cognition_handoffs",
    "facets": "l1_source_facets",
    "profiles": "embedding_profiles",
    "chunks": "l1_event_chunks",
    "entities": "l1_event_entities",
    "projection_state": "l1_event_entity_projection_state",
    "projected_entities": "l1_projected_event_entities",
    "sessions": "chat_sessions",
}


class SqliteEventStateTransfer:
    """Call only while the runtime is stopped under the maintenance lease."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    @staticmethod
    async def _export(connection: aiosqlite.Connection) -> EventStorageSnapshot:
        connection.row_factory = aiosqlite.Row
        values: dict[str, Any] = {}
        for name, table in TABLES.items():
            rows = await (await connection.execute(f"SELECT * FROM {table}")).fetchall()
            values[name] = [
                snapshot_fact(dict(row)) if name == "facts" else dict(row) for row in rows
            ]
        row = await (
            await connection.execute("SELECT seq FROM sqlite_sequence WHERE name='fact_events'")
        ).fetchone()
        values["event_sequence"] = int(row[0]) if row is not None else 0
        generation = await (
            await connection.execute(
                "SELECT clear_generation FROM l1_entity_link_projection_generation WHERE singleton_id=1"
            )
        ).fetchone()
        if generation is None:
            raise RuntimeError("L1 entity-link generation is missing")
        values["entity_link_generation"] = int(generation[0])
        return EventStorageSnapshot.model_validate(values)

    async def export_state(self) -> EventStorageSnapshot:
        async with event_connection(self._db_path, profile="readonly") as connection:
            await connection.execute("BEGIN")
            return await self._export(connection)

    async def import_state(self, snapshot: EventStorageSnapshot, *, replace: bool = False) -> None:
        snapshot = EventStorageSnapshot.model_validate(snapshot.model_dump(mode="json"))
        async with event_connection(self._db_path, profile="hot_write") as connection:
            await connection.execute("BEGIN IMMEDIATE")
            if not replace and not (await self._export(connection)).is_empty():
                raise ValueError("Destination has data; explicit replacement is required")
            for table in reversed(tuple(TABLES.values())):
                await connection.execute(f"DELETE FROM {table}")
            await connection.execute("DELETE FROM l1_events_fts")
            for name, table in TABLES.items():
                # The insert trigger creates fresh handoffs; restore the exact durable ledger instead.
                if name == "handoffs":
                    await connection.execute("DELETE FROM l1_cognition_handoffs")
                rows = [
                    fact_row(row) if name == "facts" else row.model_dump(mode="json")
                    for row in getattr(snapshot, name)
                ]
                if rows:
                    columns = tuple(rows[0])
                    await connection.executemany(
                        f"INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                        [tuple(row[column] for column in columns) for row in rows],
                    )
            for fact in snapshot.facts:
                if fact.deleted_at is None:
                    await connection.execute(
                        "INSERT INTO l1_events_fts(event_id,content) VALUES (?,?)",
                        (fact.event_id, tokenize_for_fts(fact_search_text(fact_row(fact)))),
                    )
            await connection.execute("DELETE FROM sqlite_sequence WHERE name='fact_events'")
            await connection.execute(
                "INSERT INTO sqlite_sequence(name,seq) VALUES ('fact_events',?)",
                (snapshot.event_sequence,),
            )
            await connection.execute(
                "UPDATE l1_entity_link_projection_generation SET clear_generation=? WHERE singleton_id=1",
                (snapshot.entity_link_generation,),
            )
            await connection.commit()
