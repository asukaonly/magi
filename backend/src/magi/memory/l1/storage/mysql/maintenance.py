"""MySQL lifecycle, cognition recovery and conditional evidence maintenance."""

from __future__ import annotations

from .common import MysqlEventConnection

import time
from typing import Any

from sqlalchemy import delete, func, or_, select, tuple_, update

from magi.events.events import EventTypes
from magi.memory.event_contracts import RetentionClass
from magi.memory.evidence import EvidenceStatus
from ...maintenance_contracts import (
    EvidenceAnnotationUpdate,
    EvidenceBackfillQuery,
    EventClearState,
    EventScanItem,
)
from ...ports import EventQuery
from .common import identity, record
from .queries import filters
from . import schema as s


def evidence_filters(query: EvidenceBackfillQuery, through: int) -> list:
    parts = filters(
        EventQuery(
            user_id=query.user_id,
            event_type=query.event_type,
            source_filters=query.source_filters,
            start_time=query.start_time,
            end_time=query.end_time,
        )
    )
    parts.append(s.events.c.id <= through)
    if query.stale_rule_version is not None:
        parts.append(
            or_(
                s.events.c.evidence_status != int(EvidenceStatus.CLASSIFIED),
                s.events.c.evidence_rule_version != query.stale_rule_version,
            )
        )
    return parts


class MysqlEventMaintenance(MysqlEventConnection):
    async def get_pinned_payloads(self, event_ids: list[str]) -> dict[str, str]:
        result = {}
        async with self._transaction() as connection:
            for offset in range(0, len(event_ids), 500):
                page = event_ids[offset : offset + 500]
                result.update(
                    (
                        await connection.execute(
                            select(s.payloads.c.event_id, s.payloads.c.content).where(
                                s.payloads.c.event_key.in_([identity(v) for v in page]),
                                s.payloads.c.event_id.in_(page),
                            )
                        )
                    ).all()
                )
        return result

    async def prune_pinned_payloads(self, *, retention_seconds: float, now: float) -> int:
        async with self._transaction(write=True) as connection:
            return int((
                await connection.execute(
                    delete(s.payloads).where(
                        s.payloads.c.created_at < now - float(retention_seconds)
                    )
                )
            ).rowcount)

    async def list_ready_cognition_handoffs(self, *, now: float, limit: int = 100) -> list[str]:
        async with self._transaction() as connection:
            return list(
                (
                    await connection.execute(
                        select(s.handoffs.c.event_id)
                        .where(s.handoffs.c.available_at <= now)
                        .order_by(
                            s.handoffs.c.available_at,
                            s.handoffs.c.created_at,
                            s.handoffs.c.event_id,
                        )
                        .limit(max(1, min(limit, 1000)))
                    )
                ).scalars()
            )

    async def complete_cognition_handoff(self, event_id: str) -> None:
        async with self._transaction(write=True) as connection:
            await connection.execute(
                delete(s.handoffs).where(s.handoffs.c.event_key == identity(event_id))
            )

    async def retry_cognition_handoff(self, event_id: str, *, error: str, now: float) -> None:
        async with self._transaction(write=True) as connection:
            count = (
                await connection.execute(
                    select(s.handoffs.c.attempt_count).where(
                        s.handoffs.c.event_key == identity(event_id)
                    )
                )
            ).scalar_one_or_none()
            if count is not None:
                await connection.execute(
                    update(s.handoffs)
                    .where(s.handoffs.c.event_key == identity(event_id))
                    .values(
                        attempt_count=count + 1,
                        available_at=now + min(60, 1 << min(count, 6)),
                        last_error=error[:200],
                    )
                )

    async def summarize_event_sources(self, **options: Any) -> list[dict[str, Any]]:
        query = (
            select(
                s.events.c.source,
                func.count().label("event_count"),
                func.avg(s.events.c.importance_score).label("avg_importance"),
                func.min(s.events.c.timestamp).label("min_timestamp"),
                func.max(s.events.c.timestamp).label("max_timestamp"),
            )
            .where(
                *filters(EventQuery(**options)),
                func.trim(s.events.c.source) != "",
            )
            .group_by(s.events.c.source)
            .order_by(func.count().desc(), s.events.c.source)
        )
        async with self._transaction() as connection:
            return [dict(row) for row in (await connection.execute(query)).mappings()]

    async def list_compressible_event_page(
        self, *, older_than: float, limit: int = 1000, after: tuple[float, str] | None = None
    ) -> list[tuple[float, str]]:
        query = select(s.events.c.timestamp, s.events.c.event_id).where(
            s.events.c.deleted_at.is_(None),
            s.events.c.retention_class == int(RetentionClass.COMPRESSIBLE),
            s.events.c.timestamp < older_than,
        )
        if after is not None:
            query = query.where(tuple_(s.events.c.timestamp, s.events.c.event_id) > after)
        async with self._transaction() as connection:
            return [
                (float(row[0]), str(row[1]))
                for row in (
                    await connection.execute(
                        query.order_by(s.events.c.timestamp, s.events.c.event_id).limit(limit)
                    )
                ).all()
            ]

    async def count_evidence_backfill(self, query: EvidenceBackfillQuery, *, through: int) -> int:
        async with self._transaction() as connection:
            return int(
                (
                    await connection.execute(
                        select(func.count())
                        .select_from(s.events)
                        .where(*evidence_filters(query, through))
                    )
                ).scalar_one()
            )

    async def scan_evidence_backfill(
        self, query: EvidenceBackfillQuery, *, after: int, through: int, limit: int
    ) -> list[EventScanItem]:
        result = []
        async with self._transaction() as connection:
            rows = (
                await connection.execute(
                    select(s.events)
                    .where(*evidence_filters(query, through), s.events.c.id > after)
                    .order_by(s.events.c.id)
                    .limit(limit)
                )
            ).mappings()
            for row in rows:
                try:
                    value = record(row)
                except (ValueError, TypeError, KeyError) as exc:
                    result.append(
                        EventScanItem(int(row["id"]), str(row["event_id"]), None, str(exc))
                    )
                else:
                    result.append(EventScanItem(int(row["id"]), str(row["event_id"]), value))
        return result

    async def apply_evidence_annotations(self, updates: list[EvidenceAnnotationUpdate]) -> int:
        count = 0
        async with self._transaction(write=True) as connection:
            for item in updates:
                key = identity(item.expected.event.event_id)
                row = (
                    (
                        await connection.execute(
                            select(s.events).where(
                                s.events.c.event_key == key, s.events.c.deleted_at.is_(None)
                            )
                        )
                    )
                    .mappings()
                    .first()
                )
                if row is None or record(row) != item.expected:
                    continue
                evidence = item.evidence
                await connection.execute(
                    update(s.events)
                    .where(s.events.c.event_key == key)
                    .values(
                        evidence_status=int(evidence.status),
                        evidence_class=int(evidence.classification),
                        evidence_rule_version=evidence.rule_version,
                        l1_retrieval_scope=int(evidence.retrieval_scope),
                    )
                )
                count += 1
        return count

    @staticmethod
    async def _clear_state(connection) -> EventClearState:
        generation = int(
            (
                await connection.execute(
                    select(s.state.c.clear_generation).where(s.state.c.singleton_id == 1)
                )
            ).scalar_one()
        )
        has_projected = (
            await connection.execute(select(s.projection_state.c.event_key).limit(1))
        ).first() is not None
        return EventClearState(generation, has_projected)

    async def get_clear_state(self) -> EventClearState:
        async with self._transaction() as connection:
            return await self._clear_state(connection)

    async def clear_events(self, *, entity_link_clear_generation: int | None = None) -> int:
        async with self._transaction(write=True) as connection:
            state = await self._clear_state(connection)
            generation = state.entity_link_generation
            if entity_link_clear_generation is None:
                if state.has_projected_links:
                    raise RuntimeError(
                        "L1 clear with entity-link projections requires unified memory clear"
                    )
            else:
                if entity_link_clear_generation <= generation:
                    raise RuntimeError("L1 clear must advance entity-link generation")
                generation = entity_link_clear_generation
            count = int(
                (
                    await connection.execute(
                        select(func.count())
                        .select_from(s.events)
                        .where(s.events.c.deleted_at.is_(None))
                    )
                ).scalar_one()
            )
            for table in (
                s.handoffs,
                s.payloads,
                s.facets,
                s.chunks,
                s.embeddings,
                s.profiles,
                s.projected_entities,
                s.projection_state,
                s.entities,
                s.sequences,
                s.sessions,
                s.events,
            ):
                await connection.execute(delete(table))
            await connection.execute(
                update(s.state)
                .where(s.state.c.singleton_id == 1)
                .values(clear_generation=generation, updated_at=time.time())
            )
        return count

    async def rebuild_chat_session_projection(self, session_id: str) -> None:
        async with self._transaction(write=True) as connection:
            await self._rebuild_session(connection, session_id)

    @staticmethod
    async def _rebuild_session(connection, session_id: str) -> None:
        base = [
            s.events.c.session_key == identity(session_id),
            s.events.c.session_id == session_id,
            s.events.c.deleted_at.is_(None),
            s.events.c.event_type.in_([EventTypes.USER_MESSAGE, EventTypes.AI_RESPONSE]),
        ]
        query = (
            select(s.events.c.content, s.events.c.timestamp)
            .where(*base)
            .order_by(
                s.events.c.timestamp.desc(),
                s.events.c.created_at.desc(),
                s.events.c.event_id.desc(),
            )
            .limit(1)
        )
        latest = (await connection.execute(query)).first()
        user = (
            await connection.execute(query.where(s.events.c.event_type == EventTypes.USER_MESSAGE))
        ).first()
        count = (
            await connection.execute(select(func.count()).select_from(s.events).where(*base))
        ).scalar_one()
        await connection.execute(
            update(s.sessions)
            .where(
                s.sessions.c.session_key == identity(session_id), s.sessions.c.deleted_at.is_(None)
            )
            .values(
                updated_at=latest.timestamp if latest else time.time(),
                last_message_at=latest.timestamp if latest else None,
                last_user_message_at=user.timestamp if user else None,
                last_message_preview=str(latest.content or "").strip()[:120] if latest else "",
                last_user_message_preview=str(user.content or "").strip()[:120] if user else "",
                message_count=count,
            )
        )

    async def retire_chat_session_projection(self, session_id: str, *, deleted_at: float) -> None:
        async with self._transaction(write=True) as connection:
            await connection.execute(
                update(s.sessions)
                .where(s.sessions.c.session_key == identity(session_id))
                .values(
                    title="",
                    summary="",
                    updated_at=deleted_at,
                    last_message_at=None,
                    last_user_message_at=None,
                    last_message_preview="",
                    last_user_message_preview="",
                    message_count=0,
                    workspace_path=None,
                    archived_at=None,
                    deleted_at=deleted_at,
                )
            )
