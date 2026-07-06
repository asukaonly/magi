"""Persistence operations for the L3 summary store."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...sql_search import build_like_search_clause
from ...embedding.embedding_text_builders import build_l3_embedding_text
from ...embedding.sqlite_vec_index import SqliteVecIndex
from ...hybrid_retrieval.fts_utils import tokenize_for_fts
from ..evidence.links import (
    build_summary_event_link_rows,
    build_summary_task_link_rows,
    normalize_event_ids,
    row_to_summary_event_link,
    row_to_summary_task_link,
)
from ..models import L3Candidate
from .schema import SUMMARY_CHUNKS_TABLE
from .serialization import decode_optional_json, encode_optional_json, row_to_summary_dict


class _L3SummaryPersistenceHostProtocol(Protocol):
    db_path: str
    _vector_index: SqliteVecIndex | None

    async def initialize(self) -> None: ...

    async def _schedule_summary_embedding(self, summary: Dict[str, Any]) -> None: ...


def _summary_from_new_candidate(
    candidate: L3Candidate,
    *,
    insight_key: str | None,
    now: float,
) -> Dict[str, Any]:
    return {
        "summary_id": f"summary_{uuid.uuid4().hex}",
        "summary_type": str(candidate.summary_type),
        "summary_category": str(candidate.summary_category),
        "period_start": now,
        "period_end": now,
        "content": candidate.content,
        "key_topics": [],
        "key_entities": [],
        "sentiment_summary": None,
        "change_and_pattern": None,
        "source_event_ids": list(candidate.source_event_ids),
        "source_event_count": len(candidate.source_event_ids),
        "importance_aggregate": 0.0,
        "event_type_distribution": {},
        "generated_by_model": "rule-summary",
        "generation_prompt": None,
        "generation_reason": f"{candidate.summary_type}:{candidate.summary_category}",
        "insight_key": insight_key,
        "review_state": candidate.review_state,
        "insight_metadata": dict(candidate.insight_metadata or {}),
        "narrative_style": "default",
        "essence_prose": None,
        "created_at": now,
        "updated_at": now,
    }


class L3SummaryPersistenceMixin:
    """Summary row persistence, listing, deletion, and evidence link helpers."""

    async def count_summaries(
        self,
        *,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        query: str | None = None,
    ) -> int:
        """Count summaries, optionally filtered by creation time."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        search_query = query
        sql = "SELECT COUNT(*) FROM summaries WHERE 1=1"
        args: list[Any] = []
        if start_time is not None:
            sql += " AND created_at >= ?"
            args.append(float(start_time))
        if end_time is not None:
            sql += " AND created_at < ?"
            args.append(float(end_time))
        search_sql, search_args = build_like_search_clause(
            [
                "summary_id",
                "summary_type",
                "summary_category",
                "content",
                "key_topics",
                "key_entities",
                "sentiment_summary",
                "change_and_pattern",
                "source_event_ids",
                "generated_by_model",
                "generation_prompt",
                "generation_reason",
                "insight_key",
                "review_state",
                "insight_metadata",
                "narrative_style",
                "essence_prose",
            ],
            search_query,
        )
        sql += search_sql
        args.extend(search_args)
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute(sql, tuple(args)) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_summaries(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        query: str | None = None,
    ) -> List[Dict[str, Any]]:
        """List most recent summaries."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        sql = "SELECT * FROM summaries WHERE 1=1"
        args: list[Any] = []
        search_sql, search_args = build_like_search_clause(
            [
                "summary_id",
                "summary_type",
                "summary_category",
                "content",
                "key_topics",
                "key_entities",
                "sentiment_summary",
                "change_and_pattern",
                "source_event_ids",
                "generated_by_model",
                "generation_prompt",
                "generation_reason",
                "insight_key",
                "review_state",
                "insight_metadata",
                "narrative_style",
                "essence_prose",
            ],
            query,
        )
        sql += search_sql
        args.extend(search_args)
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        args.extend([int(limit), int(offset)])
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def list_summaries_by_category(
        self,
        *,
        summary_categories: List[str],
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """List summaries scoped to one or more summary_category values within a window."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        normalized = [str(c).strip() for c in summary_categories if str(c).strip()]
        if not normalized:
            return []
        placeholders = ", ".join("?" for _ in normalized)
        sql = f"SELECT * FROM summaries WHERE summary_category IN ({placeholders})"
        args: List[Any] = list(normalized)
        if period_start is not None:
            sql += " AND period_end >= ?"
            args.append(float(period_start))
        if period_end is not None:
            sql += " AND period_start <= ?"
            args.append(float(period_end))
        sql += " ORDER BY period_end DESC, updated_at DESC LIMIT ?"
        args.append(int(limit))
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def list_summaries_older_than(
        self,
        *,
        older_than: float,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """List summaries whose covered time window ended before a cutoff."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT *
                FROM summaries
                WHERE period_end < ?
                ORDER BY period_end ASC, updated_at ASC
                LIMIT ?
                """,
                (float(older_than), int(limit)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def delete_summary(self, summary_id: str) -> bool:
        """Delete one summary together with its search/vector artifacts."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()

        chunk_ids: list[str] = []
        deleted_count = 0
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT chunk_id FROM {SUMMARY_CHUNKS_TABLE} WHERE summary_id = ?",
                (summary_id,),
            ) as cursor:
                rows = await cursor.fetchall()
            chunk_ids = [str(row["chunk_id"]) for row in rows]

            await db.execute("DELETE FROM summary_event_links WHERE summary_id = ?", (summary_id,))
            await db.execute("DELETE FROM summary_task_links WHERE summary_id = ?", (summary_id,))
            await db.execute(
                f"DELETE FROM {SUMMARY_CHUNKS_TABLE} WHERE summary_id = ?", (summary_id,)
            )
            await db.execute("DELETE FROM l3_summaries_fts WHERE summary_id = ?", (summary_id,))
            cursor = await db.execute("DELETE FROM summaries WHERE summary_id = ?", (summary_id,))
            deleted_count = int(cursor.rowcount or 0)
            await db.commit()

        if deleted_count > 0 and host._vector_index is not None:
            for chunk_id in chunk_ids:
                await host._vector_index.delete_entity(entity_id=chunk_id)
        return deleted_count > 0

    async def clear(self) -> int:
        """Delete all summaries."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM summaries") as cursor:
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
            await db.execute("DELETE FROM summary_event_links")
            await db.execute("DELETE FROM summary_task_links")
            await db.execute("DELETE FROM summaries")
            await db.execute(f"DELETE FROM {SUMMARY_CHUNKS_TABLE}")
            await db.execute("DELETE FROM l3_summaries_fts")
            await db.commit()
        if host._vector_index is not None:
            await host._vector_index.clear()
        return count

    async def upsert_candidate(
        self,
        *,
        candidate: L3Candidate,
        source_task_ids: Optional[list[str]] = None,
        summary_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist a structured L3 candidate and its evidence links.

        When ``candidate.insight_key`` is set, an existing summary with the same
        insight_key is reused: ``summary_id`` / ``created_at`` are preserved,
        ``source_event_ids`` are merged (existing order first, new ids appended),
        and ``insight_metadata`` is merged (new values overwrite). This realizes
        the design contract that recurring insights upsert by ``insight_key``
        instead of producing a new row each time the gate fires.
        """
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        now = time.time()
        insight_key, existing_summary = await self._candidate_insight_match(candidate)
        summary = self._build_candidate_summary(
            candidate=candidate,
            existing_summary=existing_summary,
            insight_key=insight_key,
            now=now,
            summary_overrides=summary_overrides,
        )
        await self._store_summary(summary)
        await self._replace_candidate_links(
            summary=summary,
            candidate=candidate,
            source_task_ids=source_task_ids or [],
        )
        return summary

    async def _candidate_insight_match(
        self,
        candidate: L3Candidate,
    ) -> tuple[str | None, Optional[Dict[str, Any]]]:
        insight_key = (candidate.insight_key or "").strip() or None
        if insight_key is None:
            return None, None
        return insight_key, await self._find_summary_by_insight_key(insight_key)

    def _build_candidate_summary(
        self,
        *,
        candidate: L3Candidate,
        existing_summary: Optional[Dict[str, Any]],
        insight_key: str | None,
        now: float,
        summary_overrides: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if existing_summary is not None:
            summary = self._summary_from_existing_candidate(
                candidate=candidate,
                existing_summary=existing_summary,
                insight_key=insight_key,
                now=now,
            )
        else:
            summary = _summary_from_new_candidate(candidate, insight_key=insight_key, now=now)
        if summary_overrides:
            summary.update(summary_overrides)
        summary.setdefault("summary_id", f"summary_{uuid.uuid4().hex}")
        summary.setdefault("created_at", now)
        summary["updated_at"] = float(summary.get("updated_at") or now)
        return summary

    def _summary_from_existing_candidate(
        self,
        *,
        candidate: L3Candidate,
        existing_summary: Dict[str, Any],
        insight_key: str | None,
        now: float,
    ) -> Dict[str, Any]:
        merged_event_ids = self._merge_source_event_ids(
            existing_summary.get("source_event_ids") or [],
            candidate.source_event_ids,
        )
        merged_metadata = self._merge_insight_metadata(
            existing_summary.get("insight_metadata"),
            candidate.insight_metadata,
        )
        return {
            "summary_id": existing_summary["summary_id"],
            "summary_type": str(candidate.summary_type),
            "summary_category": str(candidate.summary_category),
            "period_start": float(existing_summary.get("period_start") or now),
            "period_end": now,
            "content": candidate.content,
            "key_topics": list(existing_summary.get("key_topics") or []),
            "key_entities": list(existing_summary.get("key_entities") or []),
            "sentiment_summary": existing_summary.get("sentiment_summary"),
            "change_and_pattern": existing_summary.get("change_and_pattern"),
            "source_event_ids": merged_event_ids,
            "source_event_count": len(merged_event_ids),
            "importance_aggregate": float(existing_summary.get("importance_aggregate") or 0.0),
            "event_type_distribution": dict(existing_summary.get("event_type_distribution") or {}),
            "generated_by_model": existing_summary.get("generated_by_model") or "rule-summary",
            "generation_prompt": existing_summary.get("generation_prompt"),
            "generation_reason": existing_summary.get("generation_reason")
            or f"{candidate.summary_type}:{candidate.summary_category}",
            "insight_key": insight_key,
            "review_state": candidate.review_state or existing_summary.get("review_state"),
            "insight_metadata": merged_metadata,
            "narrative_style": str(existing_summary.get("narrative_style") or "default"),
            "essence_prose": existing_summary.get("essence_prose"),
            "created_at": float(existing_summary.get("created_at") or now),
            "updated_at": now,
        }

    async def _replace_candidate_links(
        self,
        *,
        summary: Dict[str, Any],
        candidate: L3Candidate,
        source_task_ids: list[str],
    ) -> None:
        link_event_ids = list(summary.get("source_event_ids") or [])
        if not link_event_ids:
            link_event_ids = list(candidate.source_event_ids)
        await self._replace_summary_event_links(summary["summary_id"], link_event_ids)
        await self._replace_summary_task_links(summary["summary_id"], source_task_ids)

    async def _find_summary_by_insight_key(self, insight_key: str) -> Optional[Dict[str, Any]]:
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM summaries WHERE insight_key = ? LIMIT 1",
                (insight_key,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    @staticmethod
    def _merge_source_event_ids(existing: List[Any], incoming: List[Any]) -> List[str]:
        merged: List[str] = []
        seen: set[str] = set()
        for source in (existing, incoming):
            for raw in source or []:
                text = str(raw).strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                merged.append(text)
        return merged

    @staticmethod
    def _merge_insight_metadata(existing: Any, incoming: Any) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        if isinstance(existing, dict):
            merged.update(existing)
        if isinstance(incoming, dict):
            merged.update(incoming)
        return merged

    async def list_summary_event_links(self, summary_id: str) -> List[Dict[str, Any]]:
        """Return event links for a summary."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT link_id, summary_id, event_id, link_role, evidence_weight, created_at
                FROM summary_event_links
                WHERE summary_id = ?
                ORDER BY created_at ASC
                """,
                (summary_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [row_to_summary_event_link(row) for row in rows]

    async def list_summary_task_links(self, summary_id: str) -> List[Dict[str, Any]]:
        """Return task links for a summary."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT link_id, summary_id, task_id, link_role, created_at
                FROM summary_task_links
                WHERE summary_id = ?
                ORDER BY created_at ASC
                """,
                (summary_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [row_to_summary_task_link(row) for row in rows]

    async def get_episodic_summary_by_episode_id(self, episode_id: str) -> Optional[Dict[str, Any]]:
        """Return the most recent L3 episodic summary linked to an L2 episode."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM summaries
                WHERE summary_category = 'episodic'
                  AND json_extract(insight_metadata, '$.source_episode_id') = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (episode_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._row_to_dict(row) if row is not None else None

    async def get_episodic_summary_by_experience_id(
        self, experience_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return the most recent L3 episodic summary linked to an L2 experience."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM summaries
                WHERE summary_category = 'episodic'
                  AND json_extract(insight_metadata, '$.source_experience_id') = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (experience_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._row_to_dict(row) if row is not None else None

    async def filter_linked_event_ids(self, event_ids: list[str]) -> list[str]:
        """Return the subset of event ids that are already covered by summary links."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        normalized_ids = normalize_event_ids(event_ids)
        if not normalized_ids:
            return []

        placeholders = ", ".join("?" for _ in normalized_ids)
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute(
                f"""
                SELECT DISTINCT event_id
                FROM summary_event_links
                WHERE event_id IN ({placeholders})
                """,
                tuple(normalized_ids),
            ) as cursor:
                rows = await cursor.fetchall()
        covered = {str(row[0]) for row in rows}
        return [event_id for event_id in normalized_ids if event_id in covered]

    async def _store_summary(self, summary: Dict[str, Any]) -> None:
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        insight_key_raw = summary.get("insight_key")
        insight_key: str | None = None
        if isinstance(insight_key_raw, str):
            stripped = insight_key_raw.strip()
            insight_key = stripped or None
        review_state_raw = summary.get("review_state")
        review_state = str(review_state_raw).strip() if isinstance(review_state_raw, str) else None
        review_state = review_state or None
        insight_metadata = self._encode_optional_json(summary.get("insight_metadata"))
        narrative_style = str(summary.get("narrative_style") or "default")
        essence_prose_raw = summary.get("essence_prose")
        essence_prose = str(essence_prose_raw) if essence_prose_raw else None
        async with sqlite_connection_async(host.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO summaries(
                    summary_id, summary_type, summary_category, period_start, period_end,
                    content, key_topics, key_entities, sentiment_summary, change_and_pattern, source_event_ids,
                    source_event_count, importance_aggregate, event_type_distribution,
                    generated_by_model, generation_prompt, generation_reason,
                    insight_key, review_state, insight_metadata,
                    narrative_style, essence_prose,
                    embedding_chunk_count, last_embedded_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary["summary_id"],
                    summary["summary_type"],
                    summary["summary_category"],
                    float(summary["period_start"]),
                    float(summary["period_end"]),
                    summary["content"],
                    json.dumps(summary["key_topics"], ensure_ascii=False),
                    json.dumps(summary["key_entities"], ensure_ascii=False),
                    self._encode_optional_json(summary["sentiment_summary"]),
                    self._encode_optional_json(summary.get("change_and_pattern")),
                    json.dumps(summary["source_event_ids"], ensure_ascii=False),
                    int(summary["source_event_count"]),
                    float(summary["importance_aggregate"]),
                    json.dumps(summary["event_type_distribution"], ensure_ascii=False),
                    summary["generated_by_model"],
                    summary["generation_prompt"],
                    summary["generation_reason"],
                    insight_key,
                    review_state,
                    insight_metadata,
                    narrative_style,
                    essence_prose,
                    int(summary.get("embedding_chunk_count") or 0),
                    (
                        float(summary["last_embedded_at"])
                        if summary.get("last_embedded_at") is not None
                        else None
                    ),
                    float(summary["created_at"]),
                    float(summary["updated_at"]),
                ),
            )
            tokenized = tokenize_for_fts(build_l3_embedding_text(summary))
            await db.execute(
                "DELETE FROM l3_summaries_fts WHERE summary_id = ?",
                (summary["summary_id"],),
            )
            await db.execute(
                "INSERT INTO l3_summaries_fts(summary_id, content) VALUES (?, ?)",
                (summary["summary_id"], tokenized),
            )
            await db.commit()
        await host._schedule_summary_embedding(summary)

    async def _replace_summary_event_links(self, summary_id: str, event_ids: list[str]) -> None:
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        now = time.time()
        async with sqlite_connection_async(host.db_path) as db:
            await db.execute("DELETE FROM summary_event_links WHERE summary_id = ?", (summary_id,))
            if event_ids:
                await db.executemany(
                    """
                    INSERT INTO summary_event_links(
                        link_id, summary_id, event_id, link_role, evidence_weight, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    build_summary_event_link_rows(
                        summary_id=summary_id,
                        event_ids=event_ids,
                        created_at=now,
                    ),
                )
            await db.commit()

    async def _replace_summary_task_links(self, summary_id: str, task_ids: list[str]) -> None:
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        now = time.time()
        async with sqlite_connection_async(host.db_path) as db:
            await db.execute("DELETE FROM summary_task_links WHERE summary_id = ?", (summary_id,))
            if task_ids:
                await db.executemany(
                    """
                    INSERT INTO summary_task_links(
                        link_id, summary_id, task_id, link_role, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    build_summary_task_link_rows(
                        summary_id=summary_id,
                        task_ids=task_ids,
                        created_at=now,
                    ),
                )
            await db.commit()

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return row_to_summary_dict(row)

    def _encode_optional_json(self, value: Any) -> str | None:
        return encode_optional_json(value)

    def _decode_optional_json(self, value: Any) -> Any:
        return decode_optional_json(value)


__all__ = ["L3SummaryPersistenceMixin"]
