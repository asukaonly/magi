"""Persistence operations for the L3 summary store."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
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


class L3SummaryPersistenceMixin:
    """Summary row persistence, listing, deletion, and evidence link helpers."""

    async def count_summaries(self) -> int:
        """Count all summaries."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM summaries") as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_summaries(self, *, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List most recent summaries."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM summaries ORDER BY updated_at DESC LIMIT ? OFFSET ?", (int(limit), int(offset))) as cursor:
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
        """Persist a structured L3 candidate and its evidence links."""
        host = cast(_L3SummaryPersistenceHostProtocol, self)
        await host.initialize()
        now = time.time()
        summary = {
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
            "created_at": now,
            "updated_at": now,
        }
        if summary_overrides:
            summary.update(summary_overrides)
        summary.setdefault("summary_id", f"summary_{uuid.uuid4().hex}")
        summary.setdefault("created_at", now)
        summary["updated_at"] = float(summary.get("updated_at") or now)
        await self._store_summary(summary)
        await self._replace_summary_event_links(summary["summary_id"], candidate.source_event_ids)
        await self._replace_summary_task_links(summary["summary_id"], source_task_ids or [])
        return summary

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
        async with sqlite_connection_async(host.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO summaries(
                    summary_id, summary_type, summary_category, period_start, period_end,
                    content, key_topics, key_entities, sentiment_summary, change_and_pattern, source_event_ids,
                    source_event_count, importance_aggregate, event_type_distribution,
                    generated_by_model, generation_prompt, generation_reason,
                    embedding_chunk_count, last_embedded_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    int(summary.get("embedding_chunk_count") or 0),
                    float(summary["last_embedded_at"]) if summary.get("last_embedded_at") is not None else None,
                    float(summary["created_at"]),
                    float(summary["updated_at"]),
                ),
            )
            tokenized = tokenize_for_fts(summary["content"])
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