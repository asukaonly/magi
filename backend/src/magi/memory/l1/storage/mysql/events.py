"""Atomic MySQL event insertion, source identity and session ordering."""

from __future__ import annotations

import json
import time

from sqlalchemy import insert, select, update

from magi.events.events import EventTypes
from ...ports import EventAppend, EventAppendResult, EventVisibility, MemoryEventRecord
from ....event_contracts import author_type_code, content_type_code
from ....evidence import L1RetrievalScope
from ...embeddings.common import embedding_status_code
from .common import MysqlEventConnection, event_select, identity, nullable_identity, record
from . import schema as s
from .queries import MysqlEventQueries
from .facets import MysqlEventFacets, facet_values
from .lexical import MysqlEventLexical
from .entities import MysqlEventEntities
from .deletion import MysqlEventDeletion
from .embeddings import MysqlEventEmbeddings
from .maintenance import MysqlEventMaintenance


class MysqlMemoryEventRepository(
    MysqlEventQueries,
    MysqlEventFacets,
    MysqlEventLexical,
    MysqlEventEntities,
    MysqlEventDeletion,
    MysqlEventEmbeddings,
    MysqlEventMaintenance,
    MysqlEventConnection,
):
    async def get(
        self, event_id: str, *, visibility: EventVisibility = "raw"
    ) -> MemoryEventRecord | None:
        if visibility not in {"raw", "active", "user_visible"}:
            raise ValueError("Unknown memory event visibility")
        query = event_select().where(
            s.events.c.event_key == identity(event_id), s.events.c.event_id == event_id
        )
        if visibility != "raw":
            query = query.where(s.events.c.deleted_at.is_(None))
        if visibility == "user_visible":
            query = query.where(s.events.c.l1_retrieval_scope != int(L1RetrievalScope.AUDIT_ONLY))
        async with self._transaction() as connection:
            row = (await connection.execute(query)).mappings().first()
        return record(row) if row is not None else None

    async def find_by_idempotency(
        self, *, source: str, event_type: str, idempotency_key: str
    ) -> str | None:
        async with self._transaction() as connection:
            return (
                await connection.execute(
                    select(s.events.c.event_id).where(
                        s.events.c.dedup_key == identity(source, event_type, idempotency_key),
                        s.events.c.source == source,
                        s.events.c.event_type == event_type,
                        s.events.c.idempotency_key == idempotency_key,
                    )
                )
            ).scalar_one_or_none()

    async def append(self, command: EventAppend) -> EventAppendResult:
        event = command.event
        event_key = identity(event.event_id)
        dedup_key = (
            identity(event.source, event.event_type, event.idempotency_key)
            if event.idempotency_key is not None
            else None
        )
        async with self._transaction(write=True) as connection:
            if event.idempotency_key:
                existing = (
                    await connection.execute(
                        select(s.events.c.event_id, s.events.c.session_seq).where(
                            s.events.c.dedup_key == dedup_key
                        )
                    )
                ).first()
                if existing is not None:
                    return EventAppendResult(str(existing.event_id), False, existing.session_seq)
            existing = (
                await connection.execute(
                    select(s.events.c.event_id, s.events.c.session_seq).where(
                        s.events.c.event_key == event_key
                    )
                )
            ).first()
            if existing is not None:
                return EventAppendResult(str(existing.event_id), False, existing.session_seq)
            sequence = event.session_seq
            session_id = str(event.session_id or "").strip()
            if session_id:
                session_key = identity(session_id)
                next_sequence = (
                    await connection.execute(
                        select(s.sequences.c.next_seq).where(
                            s.sequences.c.session_key == session_key
                        )
                    )
                ).scalar_one_or_none()
                sequence = max(int(sequence), 0) if sequence is not None else (next_sequence or 0)
                values = {
                    "next_seq": max(next_sequence or 0, sequence + 1),
                    "updated_at": time.time(),
                }
                if next_sequence is None:
                    await connection.execute(
                        insert(s.sequences).values(
                            session_key=session_key, session_id=session_id, **values
                        )
                    )
                else:
                    await connection.execute(
                        update(s.sequences)
                        .where(s.sequences.c.session_key == session_key)
                        .values(**values)
                    )
            event_sequence = (
                int(
                    (
                        await connection.execute(
                            select(s.state.c.event_sequence).where(s.state.c.singleton_id == 1)
                        )
                    ).scalar_one()
                )
                + 1
            )
            await connection.execute(
                update(s.state)
                .where(s.state.c.singleton_id == 1)
                .values(event_sequence=event_sequence)
            )
            evidence = command.evidence
            await connection.execute(
                insert(s.events).values(
                    id=event_sequence,
                    event_key=event_key,
                    dedup_key=dedup_key,
                    session_key=nullable_identity(event.session_id),
                    user_key=nullable_identity(event.user_id),
                    source_key=identity(event.source),
                    turn_key=nullable_identity(event.turn_id),
                    event_id=event.event_id,
                    timestamp=float(event.timestamp),
                    created_at=float(event.created_at),
                    event_type=event.event_type,
                    source=event.source,
                    source_item_id=event.source_item_id,
                    idempotency_key=event.idempotency_key,
                    memory_domain=int(event.memory_domain),
                    cognition_eligible=int(event.cognition_eligible),
                    retention_class=int(event.retention_class),
                    session_id=event.session_id,
                    turn_id=event.turn_id,
                    session_seq=sequence,
                    user_id=event.user_id,
                    content=event.content,
                    author_type=author_type_code(event.author_type),
                    content_type=content_type_code(event.content_type),
                    importance_score=float(event.importance_score),
                    media_path=event.media_path,
                    metadata_json=json.dumps(command.metadata)
                    if command.metadata is not None
                    else None,
                    deleted_at=None,
                    evidence_status=int(evidence.status),
                    evidence_class=int(evidence.classification),
                    evidence_rule_version=evidence.rule_version,
                    l1_retrieval_scope=int(evidence.retrieval_scope),
                    search_text=command.search_text,
                )
            )
            await self._append_side_rows(connection, command, event_key)
        return EventAppendResult(event.event_id, True, sequence)

    async def _append_side_rows(self, connection, command: EventAppend, event_key: str) -> None:
        event = command.event
        await connection.execute(
            insert(s.embeddings).values(
                event_key=event_key,
                event_id=event.event_id,
                embedding_status=embedding_status_code(command.embedding_status),
                embedding_profile_id=command.embedding_profile_id,
                embedding_chunk_count=0,
                last_embedded_at=None,
                updated_at=time.time(),
            )
        )
        if event.pinned_payload:
            await connection.execute(
                insert(s.payloads).values(
                    event_key=event_key,
                    event_id=event.event_id,
                    content=event.pinned_payload,
                    created_at=float(event.created_at),
                )
            )
        if event.cognition_eligible:
            await connection.execute(
                insert(s.handoffs).values(
                    event_key=event_key,
                    event_id=event.event_id,
                    created_at=float(event.created_at),
                    available_at=0,
                    attempt_count=0,
                )
            )
        for facet in command.source_facets:
            await connection.execute(insert(s.facets).values(**facet_values(facet)))
        await self._project_session(connection, event)

    @staticmethod
    async def _project_session(connection, event) -> None:
        user_id, session_id, content = (
            str(value or "").strip() for value in (event.user_id, event.session_id, event.content)
        )
        if not user_id or not session_id or not content:
            return
        session_key = identity(session_id)
        existing = (
            await connection.execute(
                select(s.sessions.c.session_key).where(s.sessions.c.session_key == session_key)
            )
        ).first()
        if existing is None:
            await connection.execute(
                insert(s.sessions).values(
                    session_key=session_key,
                    session_id=session_id,
                    user_id=user_id,
                    title="",
                    title_overridden=0,
                    summary="",
                    created_at=float(event.timestamp),
                    updated_at=float(event.timestamp),
                    last_message_at=None,
                    last_user_message_at=None,
                    last_message_preview="",
                    last_user_message_preview="",
                    message_count=0,
                )
            )
        if event.event_type not in {EventTypes.USER_MESSAGE, EventTypes.AI_RESPONSE}:
            return
        values = {
            "updated_at": float(event.timestamp),
            "last_message_at": float(event.timestamp),
            "last_message_preview": content[:120],
            "message_count": s.sessions.c.message_count + 1,
        }
        if event.event_type == EventTypes.USER_MESSAGE:
            values.update(
                last_user_message_at=float(event.timestamp), last_user_message_preview=content[:120]
            )
        await connection.execute(
            update(s.sessions)
            .where(
                s.sessions.c.session_key == session_key,
                s.sessions.c.user_id == user_id,
                s.sessions.c.deleted_at.is_(None),
            )
            .values(**values)
        )
