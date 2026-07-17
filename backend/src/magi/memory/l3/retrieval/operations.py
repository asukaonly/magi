"""Search operations for the L3 summary store."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Protocol, Tuple, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...hybrid_retrieval.fts_utils import escape_fts_query, tokenize_for_fts
from ..source_event_governance import active_summary_predicate
from .search import (
    build_fetch_by_ids_query,
    build_keyword_search_query,
    fts_backfill_row,
    fused_summary_ids,
    ids_from_rows,
    ordered_summary_dicts_from_rows,
    rows_to_bm25_pairs,
    search_path_ids,
)

logger = logging.getLogger(__name__)


class _L3SummarySearchHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    async def vector_search(
        self,
        *,
        query: str,
        summary_type: Optional[str] = None,
        summary_category: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]: ...


class L3SummarySearchMixin:
    """BM25, keyword, semantic fusion, and summary fetch helpers."""

    async def search_summaries(
        self,
        *,
        query: str,
        summary_type: Optional[str] = None,
        summary_category: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search summaries using BM25 + vector + keyword fusion."""
        host = cast(_L3SummarySearchHostProtocol, self)
        await host.initialize()
        if not query.strip():
            return []

        fetch_k = max(int(limit) * 5, 20)
        bm25_task = asyncio.ensure_future(
            self.bm25_search(
                query,
                summary_type=summary_type,
                summary_category=summary_category,
                limit=fetch_k,
            )
        )
        semantic_task = asyncio.ensure_future(
            host.vector_search(
                query=query,
                summary_type=summary_type,
                summary_category=summary_category,
                limit=fetch_k,
            )
        )
        keyword_task = asyncio.ensure_future(
            self.keyword_search(
                query=query,
                summary_type=summary_type,
                summary_category=summary_category,
                limit=fetch_k,
            )
        )

        results_or_errors = await asyncio.gather(
            bm25_task, semantic_task, keyword_task, return_exceptions=True
        )

        bm25_ids, semantic_ids, keyword_ids = search_path_ids(results_or_errors)

        for index, result in enumerate(results_or_errors):
            if isinstance(result, BaseException):
                logger.warning("L3 search path %d failed: %s", index, result)

        if not bm25_ids and not semantic_ids and not keyword_ids:
            return []

        summary_ids = fused_summary_ids(
            bm25_ids=bm25_ids,
            semantic_ids=semantic_ids,
            keyword_ids=keyword_ids,
            fetch_k=fetch_k,
        )
        if not summary_ids:
            return []
        summaries = await self.fetch_by_ids(
            summary_ids,
            summary_type=summary_type,
            summary_category=summary_category,
        )
        return summaries[:limit]

    async def bm25_search(
        self,
        query: str,
        *,
        summary_type: Optional[str] = None,
        summary_category: Optional[str] = None,
        limit: int = 20,
    ) -> List[Tuple[str, float]]:
        """Search L3 summaries via FTS5 BM25 ranking.

        Returns a list of (summary_id, bm25_score) tuples ordered by relevance.
        """
        host = cast(_L3SummarySearchHostProtocol, self)
        await host.initialize()
        tokenized = tokenize_for_fts(query)
        if not tokenized:
            return []
        escaped = escape_fts_query(tokenized)
        if not escaped:
            return []
        async with sqlite_connection_async(host.db_path) as db:
            try:
                async with db.execute(
                    f"""
                    SELECT l3_summaries_fts.summary_id, bm25(l3_summaries_fts) AS score
                    FROM l3_summaries_fts
                    JOIN summaries ON summaries.summary_id = l3_summaries_fts.summary_id
                    WHERE l3_summaries_fts MATCH ?
                      AND {active_summary_predicate("summaries")}
                      AND (? IS NULL OR summaries.summary_type = ?)
                      AND (? IS NULL OR summaries.summary_category = ?)
                    ORDER BY score
                    LIMIT ?
                    """,
                    (
                        escaped,
                        summary_type,
                        summary_type,
                        summary_category,
                        summary_category,
                        limit,
                    ),
                ) as cursor:
                    rows = await cursor.fetchall()
                return rows_to_bm25_pairs(rows)
            except Exception as exc:
                logger.warning("FTS5 BM25 search failed for L3 summaries: %s", exc)
                return []

    async def backfill_fts(self, *, batch_size: int = 500) -> int:
        """Backfill FTS5 index from existing summaries rows."""
        host = cast(_L3SummarySearchHostProtocol, self)
        await host.initialize()
        indexed = 0
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(f"""
                SELECT * FROM summaries
                WHERE {active_summary_predicate()}
                  AND summary_id NOT IN (SELECT summary_id FROM l3_summaries_fts)
                """) as cursor:
                batch: list[tuple[str, str]] = []
                async for row in cursor:
                    batch.append(fts_backfill_row(row))
                    if len(batch) >= batch_size:
                        await db.executemany(
                            "INSERT INTO l3_summaries_fts(summary_id, content) VALUES (?, ?)",
                            batch,
                        )
                        indexed += len(batch)
                        batch.clear()
                if batch:
                    await db.executemany(
                        "INSERT INTO l3_summaries_fts(summary_id, content) VALUES (?, ?)",
                        batch,
                    )
                    indexed += len(batch)
            await db.commit()
        return indexed

    async def keyword_search(
        self,
        *,
        query: str,
        summary_type: Optional[str] = None,
        summary_category: Optional[str] = None,
        limit: int = 50,
    ) -> List[str]:
        """Return summary IDs matching *query* via LIKE keyword search."""
        host = cast(_L3SummarySearchHostProtocol, self)
        sql, args = build_keyword_search_query(
            query=query,
            summary_type=summary_type,
            summary_category=summary_category,
            limit=limit,
        )
        async with sqlite_connection_async(host.db_path) as db:
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return ids_from_rows(rows)

    async def fetch_by_ids(
        self,
        summary_ids: List[str],
        *,
        summary_type: Optional[str] = None,
        summary_category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not summary_ids:
            return []
        host = cast(_L3SummarySearchHostProtocol, self)
        sql, args = build_fetch_by_ids_query(
            summary_ids=summary_ids,
            summary_type=summary_type,
            summary_category=summary_category,
        )
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return ordered_summary_dicts_from_rows(rows=rows, summary_ids=summary_ids)


__all__ = ["L3SummarySearchMixin"]
