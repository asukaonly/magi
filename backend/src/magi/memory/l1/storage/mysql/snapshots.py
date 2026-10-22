"""Atomic MySQL logical state transfer, without copying storage identities."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, insert, select, update

from ...storage_snapshot import EventStorageSnapshot
from ..snapshot_mapping import fact_row, fact_search_text, snapshot_fact
from .common import MysqlEventConnection, identity, nullable_identity
from . import schema as s

TABLES = {
    "facts": s.events,
    "sequences": s.sequences,
    "embeddings": s.embeddings,
    "payloads": s.payloads,
    "handoffs": s.handoffs,
    "facets": s.facets,
    "profiles": s.profiles,
    "chunks": s.chunks,
    "entities": s.entities,
    "projection_state": s.projection_state,
    "projected_entities": s.projected_entities,
    "sessions": s.sessions,
}


def mapped_row(name: str, value) -> dict[str, Any]:
    values = fact_row(value) if name == "facts" else value.model_dump(mode="json")
    if "event_id" in values:
        values["event_key"] = identity(values["event_id"])
    if "session_id" in values:
        values["session_key"] = nullable_identity(values["session_id"])
    if "entity_id" in values:
        values["entity_key"] = identity(values["entity_id"])
    if name == "facts":
        values.update(
            user_key=nullable_identity(values["user_id"]),
            source_key=identity(values["source"]),
            turn_key=nullable_identity(values["turn_id"]),
            dedup_key=identity(values["source"], values["event_type"], values["idempotency_key"])
            if values["idempotency_key"] is not None
            else None,
            search_text=fact_search_text(values),
        )
    if name == "facets":
        values.update(
            source_key=identity(values["source"]),
            facet_key=identity(values["facet_name"]),
            text_key=nullable_identity(values["normalized_text_value"]),
        )
    if name == "profiles":
        values["profile_key"] = identity(values["profile_id"])
    if name == "chunks":
        values["chunk_key"] = identity(values["chunk_id"])
    return values


class MysqlEventStateTransfer(MysqlEventConnection):
    """Use the same owner lock as live repositories for complete import rollback."""

    @staticmethod
    async def _export(connection) -> EventStorageSnapshot:
        values: dict[str, Any] = {}
        for name, table in TABLES.items():
            records = (await connection.execute(select(table))).mappings().all()
            if name == "facts":
                values[name] = [snapshot_fact(dict(row)) for row in records]
            else:
                record_type = EventStorageSnapshot.model_fields[name].annotation.__args__[0]
                names = tuple(record_type.model_fields)
                values[name] = [{key: row[key] for key in names} for row in records]
        state = (
            (await connection.execute(select(s.state).where(s.state.c.singleton_id == 1)))
            .mappings()
            .one()
        )
        values["event_sequence"] = int(state["event_sequence"])
        values["entity_link_generation"] = int(state["clear_generation"])
        snapshot: EventStorageSnapshot = EventStorageSnapshot.model_validate(values)
        return snapshot

    async def export_state(self) -> EventStorageSnapshot:
        async with self._transaction() as connection:
            return await self._export(connection)

    async def import_state(self, snapshot: EventStorageSnapshot, *, replace: bool = False) -> None:
        snapshot = EventStorageSnapshot.model_validate(snapshot.model_dump(mode="json"))
        async with self._transaction(write=True) as connection:
            if not replace and not (await self._export(connection)).is_empty():
                raise ValueError("Destination has data; explicit replacement is required")
            for table in reversed(tuple(TABLES.values())):
                await connection.execute(delete(table))
            for name, table in TABLES.items():
                records = getattr(snapshot, name)
                for offset in range(0, len(records), 250):
                    await connection.execute(
                        insert(table),
                        [mapped_row(name, row) for row in records[offset : offset + 250]],
                    )
            await connection.execute(
                update(s.state)
                .where(s.state.c.singleton_id == 1)
                .values(
                    event_sequence=snapshot.event_sequence,
                    clear_generation=snapshot.entity_link_generation,
                )
            )
