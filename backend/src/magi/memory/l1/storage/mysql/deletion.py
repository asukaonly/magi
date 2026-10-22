"""MySQL event deletion scopes and tombstone-safe physical retirement."""

from __future__ import annotations

import math

from sqlalchemy import and_, delete, func, or_, select, update

from ...ports import EventDeletionPlan
from .common import identity
from .entities import effective_links
from . import schema as s


class MysqlEventDeletion:
    @staticmethod
    async def _selected(
        connection, event_ids: list[str], *, only_deleted: bool = False
    ) -> list[str]:
        selected = set()
        for offset in range(0, len(event_ids), 500):
            page = event_ids[offset : offset + 500]
            query = select(s.events.c.event_id).where(
                s.events.c.event_key.in_([identity(v) for v in page]), s.events.c.event_id.in_(page)
            )
            if only_deleted:
                query = query.where(s.events.c.deleted_at.is_not(None))
            selected.update((await connection.execute(query)).scalars())
        return [key for key in dict.fromkeys(event_ids) if key in selected]

    async def prepare_event_deletion(
        self, event_ids: list[str], *, only_deleted: bool = False
    ) -> EventDeletionPlan:
        chunks = []
        async with self._transaction() as connection:
            selected = await self._selected(connection, event_ids, only_deleted=only_deleted)
            for offset in range(0, len(selected), 500):
                chunks.extend(
                    (
                        await connection.execute(
                            select(s.chunks.c.chunk_id).where(
                                s.chunks.c.event_key.in_(
                                    [identity(v) for v in selected[offset : offset + 500]]
                                ),
                            )
                        )
                    ).scalars()
                )
        return EventDeletionPlan(tuple(selected), tuple(sorted(chunks)))

    async def soft_delete_events(self, event_ids: list[str], *, deleted_at: float) -> int:
        count = 0
        async with self._transaction(write=True) as connection:
            for offset in range(0, len(event_ids), 500):
                keys = [identity(v) for v in event_ids[offset : offset + 500]]
                count += (
                    await connection.execute(
                        update(s.events)
                        .where(s.events.c.event_key.in_(keys), s.events.c.deleted_at.is_(None))
                        .values(deleted_at=deleted_at)
                    )
                ).rowcount
                await connection.execute(delete(s.chunks).where(s.chunks.c.event_key.in_(keys)))
                await connection.execute(delete(s.handoffs).where(s.handoffs.c.event_key.in_(keys)))
        return count

    async def purge_deleted_events(self, event_ids: list[str]) -> int:
        async with self._transaction(write=True) as connection:
            selected = await self._selected(connection, event_ids, only_deleted=True)
            for offset in range(0, len(selected), 500):
                keys = [identity(v) for v in selected[offset : offset + 500]]
                for table in (
                    s.handoffs,
                    s.projected_entities,
                    s.projection_state,
                    s.entities,
                    s.facets,
                    s.chunks,
                    s.embeddings,
                    s.payloads,
                    s.events,
                ):
                    await connection.execute(delete(table).where(table.c.event_key.in_(keys)))
        return len(selected)

    async def _ids(
        self, conditions: list, *, active: bool, after_event_id: str, limit: int
    ) -> list[str]:
        query = select(s.events.c.event_id).where(
            *conditions, s.events.c.event_id > str(after_event_id)
        )
        if active:
            query = query.where(s.events.c.deleted_at.is_(None))
        async with self._transaction() as connection:
            return list(
                (
                    await connection.execute(
                        query.order_by(s.events.c.event_id).limit(max(1, min(int(limit), 1000)))
                    )
                ).scalars()
            )

    async def _by_entity(
        self, entity_id: str, *, active: bool, after_event_id: str = "", limit: int = 500
    ) -> list[str]:
        entity_id = str(entity_id).strip()
        if not entity_id:
            raise ValueError("Entity ID must not be empty")
        links = effective_links()
        condition = s.events.c.event_key.in_(
            select(links.c.event_key).where(
                links.c.entity_key == identity(entity_id), links.c.entity_id == entity_id
            )
        )
        return await self._ids(
            [condition], active=active, after_event_id=after_event_id, limit=limit
        )

    async def list_active_event_ids_by_entity(
        self, entity_id: str, *, after_event_id: str = "", limit: int = 500
    ) -> list[str]:
        return await self._by_entity(
            entity_id, active=True, after_event_id=after_event_id, limit=limit
        )

    async def list_raw_event_ids_by_entity(
        self, entity_id: str, *, after_event_id: str = "", limit: int = 500
    ) -> list[str]:
        return await self._by_entity(
            entity_id, active=False, after_event_id=after_event_id, limit=limit
        )

    async def _by_time(
        self, *, start: float, end: float, active: bool, after_event_id: str = "", limit: int = 500
    ) -> list[str]:
        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError("Time range must be finite")
        if end <= start:
            raise ValueError("End must be greater than start")
        return await self._ids(
            [s.events.c.timestamp.between(start, end)],
            active=active,
            after_event_id=after_event_id,
            limit=limit,
        )

    async def list_active_event_ids_by_time_range(
        self, *, start: float, end: float, after_event_id: str = "", limit: int = 500
    ) -> list[str]:
        return await self._by_time(
            start=start, end=end, active=True, after_event_id=after_event_id, limit=limit
        )

    async def list_raw_event_ids_by_time_range(
        self, *, start: float, end: float, after_event_id: str = "", limit: int = 500
    ) -> list[str]:
        return await self._by_time(
            start=start, end=end, active=False, after_event_id=after_event_id, limit=limit
        )

    async def _by_chat(
        self,
        *,
        active: bool,
        user_id: str,
        session_id: str | None = None,
        turn_ids: list[str] | tuple[str, ...] = (),
        message_ids: list[str] | tuple[str, ...] = (),
        include_session: bool = True,
        exact_message: bool = False,
        after_event_id: str = "",
        limit: int = 500,
    ) -> list[str]:
        user, session = str(user_id or "").strip(), str(session_id or "").strip()
        turns = list(dict.fromkeys(str(v).strip() for v in turn_ids if str(v).strip()))
        messages = list(dict.fromkeys(str(v).strip() for v in message_ids if str(v).strip()))
        if not user:
            raise ValueError("User ID must not be empty")
        clauses = []
        if session and include_session:
            clauses.append(
                and_(s.events.c.session_key == identity(session), s.events.c.session_id == session)
            )
        if turns:
            clauses.append(
                and_(
                    s.events.c.turn_key.in_([identity(v) for v in turns]),
                    s.events.c.turn_id.in_(turns),
                )
            )
        if messages:
            clauses.append(s.events.c.source_item_id.in_(messages))
        if exact_message:
            if not session or not messages:
                raise ValueError("Chat user, session, and message IDs must not be empty")
            clauses = [
                and_(
                    s.events.c.session_key == identity(session),
                    s.events.c.session_id == session,
                    s.events.c.source_item_id.in_(messages),
                )
            ]
        if not clauses:
            return []
        owner = or_(
            s.events.c.user_id == user,
            s.events.c.user_id.is_(None),
            func.trim(s.events.c.user_id) == "",
        )
        return await self._ids(
            [owner, or_(*clauses)], active=active, after_event_id=after_event_id, limit=limit
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
        return await self._by_chat(
            active=True,
            user_id=user_id,
            session_id=session_id,
            turn_ids=turn_ids,
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
        return await self._by_chat(
            active=False,
            user_id=user_id,
            session_id=session_id,
            turn_ids=turn_ids,
            message_ids=message_ids,
            include_session=include_session,
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
        return await self._by_chat(
            active=True,
            user_id=user_id,
            session_id=session_id,
            message_ids=(message_id,),
            exact_message=True,
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
        return await self._by_chat(
            active=False,
            user_id=user_id,
            session_id=session_id,
            message_ids=(message_id,),
            include_session=False,
            after_event_id=after_event_id,
            limit=limit,
        )
