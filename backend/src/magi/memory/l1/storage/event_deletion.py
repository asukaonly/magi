"""SQLite owner for deletion scopes, tombstones and physical event retirement."""

from __future__ import annotations

import json
import math
from typing import Any
import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..ports import EventDeletionPlan
from ..embeddings.common import FACT_EVENTS_TABLE, EVENT_CHUNKS_TABLE, L1_EVENT_EMBEDDING_STATE_TABLE
from .event_payloads import L1_EVENT_PAYLOAD_TABLE


class SqliteEventDeletion:
    _db_path: str

    async def prepare_event_deletion(
        self, event_ids: list[str], *, only_deleted: bool = False,
    ) -> EventDeletionPlan:
        payload = json.dumps(event_ids, ensure_ascii=False, separators=(",", ":"))
        condition = "AND deleted_at IS NOT NULL" if only_deleted else ""
        async with sqlite_connection_async(self._db_path) as db:
            await db.execute("BEGIN")
            async with db.execute(
                "SELECT event_id FROM fact_events WHERE event_id IN "
                f"(SELECT CAST(value AS TEXT) FROM json_each(?)) {condition}", (payload,),
            ) as cursor:
                selected = {str(row[0]) for row in await cursor.fetchall()}
            ordered = tuple(event_id for event_id in dict.fromkeys(event_ids) if event_id in selected)
            chunks = await _chunk_ids_for_events(db, list(ordered)) if ordered else []
        return EventDeletionPlan(ordered, tuple(chunks))

    async def soft_delete_events(self, event_ids: list[str], *, deleted_at: float) -> int:
        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            changed = await _soft_delete_event_rows(db, event_ids=event_ids, deleted_at=deleted_at)
            await db.commit()
            return changed

    async def purge_deleted_events(self, event_ids: list[str]) -> int:
        async with sqlite_connection_async(self._db_path, profile="hot_write") as db:
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT event_id FROM fact_events WHERE deleted_at IS NOT NULL "
                "AND event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))",
                (json.dumps(event_ids),),
            ) as cursor:
                selected = [str(row[0]) for row in await cursor.fetchall()]
            if not selected:
                return 0
            payload = json.dumps(selected)
            for table in (
                "l1_events_fts", "l1_projected_event_entities", "l1_event_entity_projection_state",
                "l1_event_entities", "l1_source_facets", EVENT_CHUNKS_TABLE,
                L1_EVENT_EMBEDDING_STATE_TABLE, L1_EVENT_PAYLOAD_TABLE,
            ):
                await db.execute(
                    f"DELETE FROM {table} WHERE event_id IN "
                    "(SELECT CAST(value AS TEXT) FROM json_each(?))", (payload,),
                )
            deleted = await db.execute(
                "DELETE FROM fact_events WHERE deleted_at IS NOT NULL AND event_id IN "
                "(SELECT CAST(value AS TEXT) FROM json_each(?))", (payload,),
            )
            await db.commit()
            return max(int(deleted.rowcount or 0), 0)

    async def list_active_event_ids_by_entity(
        self,
        entity_id: str,
        *,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        """Return one stable page of active events linked to an entity."""
        normalized_entity_id = str(entity_id).strip()
        if not normalized_entity_id:
            raise ValueError("entity_id must not be empty")
        return await _list_active_event_ids(
            self._db_path,
            selector_sql=f"""
                SELECT events.event_id
                FROM {FACT_EVENTS_TABLE} AS events
                INNER JOIN l1_effective_event_entities AS links
                    ON links.event_id = events.event_id
                WHERE events.deleted_at IS NULL
                  AND links.entity_id = ?
                  AND events.event_id > ?
                ORDER BY events.event_id
                LIMIT ?
            """,
            selector_args=(normalized_entity_id,),
            after_event_id=after_event_id,
            limit=limit,
        )


    async def list_raw_event_ids_by_entity(
        self,
        entity_id: str,
        *,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        """Return raw entity-linked rows, including previously hidden events."""
        normalized_entity_id = str(entity_id).strip()
        if not normalized_entity_id:
            raise ValueError("entity_id must not be empty")
        return await _list_event_ids(
            self._db_path,
            selector_sql=f"""
                SELECT events.event_id
                FROM {FACT_EVENTS_TABLE} AS events
                INNER JOIN l1_effective_event_entities AS links
                    ON links.event_id = events.event_id
                WHERE links.entity_id = ?
                  AND events.event_id > ?
                ORDER BY events.event_id
                LIMIT ?
            """,
            selector_args=(normalized_entity_id,),
            after_event_id=after_event_id,
            limit=limit,
        )


    async def list_active_event_ids_by_time_range(
        self,
        *,
        start: float,
        end: float,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        """Return one stable page of active events in an inclusive time range."""
        range_start = float(start)
        range_end = float(end)
        if not math.isfinite(range_start) or not math.isfinite(range_end):
            raise ValueError("time range must be finite")
        if range_end <= range_start:
            raise ValueError("end must be greater than start")
        return await _list_active_event_ids(
            self._db_path,
            selector_sql=f"""
                SELECT event_id
                FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                  AND timestamp >= ? AND timestamp <= ?
                  AND event_id > ?
                ORDER BY event_id
                LIMIT ?
            """,
            selector_args=(range_start, range_end),
            after_event_id=after_event_id,
            limit=limit,
        )


    async def list_raw_event_ids_by_time_range(
        self,
        *,
        start: float,
        end: float,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        """Return raw rows in an inclusive time range, including hidden rows."""
        range_start = float(start)
        range_end = float(end)
        if not math.isfinite(range_start) or not math.isfinite(range_end):
            raise ValueError("time range must be finite")
        if range_end <= range_start:
            raise ValueError("end must be greater than start")
        return await _list_event_ids(
            self._db_path,
            selector_sql=f"""
                SELECT event_id
                FROM {FACT_EVENTS_TABLE}
                WHERE timestamp >= ? AND timestamp <= ?
                  AND event_id > ?
                ORDER BY event_id
                LIMIT ?
            """,
            selector_args=(range_start, range_end),
            after_event_id=after_event_id,
            limit=limit,
        )


    async def list_active_event_ids_by_chat_sources(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        turn_ids: list[str] | tuple[str, ...] = (),
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        """Return active events projected from one chat session or its turns."""
        normalized_user_id = str(user_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_turn_ids = list(
            dict.fromkeys(str(turn_id).strip() for turn_id in turn_ids if str(turn_id).strip())
        )
        if not normalized_user_id:
            raise ValueError("user_id must not be empty")
        if not normalized_session_id and not normalized_turn_ids:
            return []
        selector_parts: list[str] = []
        selector_args: list[Any] = []
        if normalized_session_id:
            selector_parts.append("session_id = ?")
            selector_args.append(normalized_session_id)
        if normalized_turn_ids:
            selector_parts.append("turn_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))")
            selector_args.append(
                json.dumps(normalized_turn_ids, ensure_ascii=False, separators=(",", ":"))
            )
        return await _list_active_event_ids(
            self._db_path,
            selector_sql=f"""
                SELECT event_id
                FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                  AND (user_id = ? OR user_id IS NULL OR TRIM(user_id) = '')
                  AND ({' OR '.join(selector_parts)})
                  AND event_id > ?
                ORDER BY event_id
                LIMIT ?
            """,
            selector_args=(normalized_user_id, *selector_args),
            after_event_id=after_event_id,
            limit=limit,
        )


    async def list_raw_event_ids_by_chat_sources(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        turn_ids: list[str] | tuple[str, ...] = (),
        message_ids: list[str] | tuple[str, ...] = (),
        include_session: bool = True,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        """Return raw chat projections for an exact owner and source snapshot."""
        normalized_user_id = str(user_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_turn_ids = list(
            dict.fromkeys(str(item).strip() for item in turn_ids if str(item).strip())
        )
        normalized_message_ids = list(
            dict.fromkeys(str(item).strip() for item in message_ids if str(item).strip())
        )
        if not normalized_user_id:
            raise ValueError("user_id must not be empty")
        selector_parts: list[str] = []
        selector_args: list[Any] = []
        if include_session and normalized_session_id:
            selector_parts.append("session_id = ?")
            selector_args.append(normalized_session_id)
        if normalized_turn_ids:
            selector_parts.append("turn_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))")
            selector_args.append(
                json.dumps(normalized_turn_ids, ensure_ascii=False, separators=(",", ":"))
            )
        if normalized_message_ids:
            selector_parts.append(
                "source_item_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))"
            )
            selector_args.append(
                json.dumps(normalized_message_ids, ensure_ascii=False, separators=(",", ":"))
            )
        if not selector_parts:
            return []
        return await _list_event_ids(
            self._db_path,
            selector_sql=f"""
                SELECT event_id
                FROM {FACT_EVENTS_TABLE}
                WHERE (user_id = ? OR user_id IS NULL OR TRIM(user_id) = '')
                  AND ({' OR '.join(selector_parts)})
                  AND event_id > ?
                ORDER BY event_id
                LIMIT ?
            """,
            selector_args=(normalized_user_id, *selector_args),
            after_event_id=after_event_id,
            limit=limit,
        )


    async def list_active_event_ids_by_chat_message(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        """Return active events projected from exactly one chat message."""
        normalized_user_id = str(user_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_message_id = str(message_id or "").strip()
        if not normalized_user_id or not normalized_session_id or not normalized_message_id:
            raise ValueError("Chat user, session, and message IDs must not be empty")
        return await _list_active_event_ids(
            self._db_path,
            selector_sql=f"""
                SELECT event_id
                FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                  AND (user_id = ? OR user_id IS NULL OR TRIM(user_id) = '')
                  AND session_id = ?
                  AND source_item_id = ?
                  AND event_id > ?
                ORDER BY event_id
                LIMIT ?
            """,
            selector_args=(normalized_user_id, normalized_session_id, normalized_message_id),
            after_event_id=after_event_id,
            limit=limit,
        )


    async def list_raw_event_ids_by_chat_message(
        self,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        """Return raw rows projected from one owner's exact chat message."""
        return await self.list_raw_event_ids_by_chat_sources(
            user_id=user_id,
            session_id=session_id,
            message_ids=(message_id,),
            include_session=False,
            after_event_id=after_event_id,
            limit=limit,
        )



async def _list_active_event_ids(
    db_path: str,
    *,
    selector_sql: str,
    selector_args: tuple[Any, ...],
    after_event_id: str,
    limit: int,
) -> list[str]:
    return await _list_event_ids(
        db_path,
        selector_sql=selector_sql,
        selector_args=selector_args,
        after_event_id=after_event_id,
        limit=limit,
    )


async def _list_event_ids(
    db_path: str,
    *,
    selector_sql: str,
    selector_args: tuple[Any, ...],
    after_event_id: str,
    limit: int,
) -> list[str]:
    page_size = max(1, min(int(limit), 1000))
    async with sqlite_connection_async(db_path, profile="hot_write") as db:
        async with db.execute(
            selector_sql,
            (*selector_args, str(after_event_id), page_size),
        ) as cursor:
            return [str(row[0]) for row in await cursor.fetchall()]


async def _soft_delete_event_rows(
    db: aiosqlite.Connection,
    *,
    event_ids: list[str],
    deleted_at: float,
) -> int:
    """Soft-delete one bounded event batch after external vectors are gone."""
    event_ids_json = json.dumps(event_ids, ensure_ascii=False, separators=(",", ":"))
    updated = await db.execute(
        f"""
        UPDATE {FACT_EVENTS_TABLE}
        SET deleted_at = ?
        WHERE deleted_at IS NULL
          AND event_id IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        """,
        (deleted_at, event_ids_json),
    )
    await db.execute(
        """
        DELETE FROM l1_events_fts
        WHERE event_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )
        """,
        (event_ids_json,),
    )
    await db.execute(
        f"""
        DELETE FROM {EVENT_CHUNKS_TABLE}
        WHERE event_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )
        """,
        (event_ids_json,),
    )
    return max(int(updated.rowcount or 0), 0)


async def _chunk_ids_for_events(
    db: aiosqlite.Connection,
    event_ids: list[str],
) -> list[str]:
    event_ids_json = json.dumps(event_ids, ensure_ascii=False, separators=(",", ":"))
    async with db.execute(
        f"""
        SELECT chunk_id
        FROM {EVENT_CHUNKS_TABLE}
        WHERE event_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )
        ORDER BY chunk_id
        """,
        (event_ids_json,),
    ) as cursor:
        return [str(row[0]) for row in await cursor.fetchall()]
