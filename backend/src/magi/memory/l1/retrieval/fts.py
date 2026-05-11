"""FTS5 and BM25 helpers for the canonical L1 event store."""

from __future__ import annotations

import logging
import re
from typing import Any, List, Protocol, Tuple, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...embedding.embedding_text_builders import build_l1_retrieval_terms_text
from ...event_contracts import MemoryEvent, author_type_label, content_type_label
from ...evidence import L1RetrievalScope
from ...hybrid_retrieval.fts_utils import (
    build_exact_fts_query,
    build_or_fts_query,
    build_stemmed_fts_query,
    escape_fts_query,
    tokenize_for_fts,
)

FACT_EVENTS_TABLE = "fact_events"

logger = logging.getLogger(__name__)


class _L1EventFtsHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...


class L1EventFtsMixin:
    """FTS5 indexing and BM25 search helpers."""

    async def bm25_search(
        self,
        query: str,
        *,
        limit: int = 20,
        user_id: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        strict: bool = False,
        l1_retrieval_scopes: list[str] | None = None,
    ) -> List[Tuple[str, float]]:
        """Search L1 events via FTS5 BM25 ranking.

        Returns a list of (event_id, bm25_score) tuples ordered by relevance.
        Lower bm25 scores indicate higher relevance in SQLite FTS5.

        When *user_id* is provided the results are scoped to events owned by
        that user via a JOIN with the fact_events table.

        When *strict* is True the search uses exact token matching first
        (no prefix stemming) and skips the OR / relaxed fallback phases.
        This avoids noise from short prefix stems such as ``crow*`` matching
        unrelated words like *crowd* or *crowded*.
        """
        host = cast(_L1EventFtsHostProtocol, self)
        await host.initialize()
        tokenized = tokenize_for_fts(query)
        if not tokenized:
            return []
        escaped = escape_fts_query(tokenized)
        if not escaped:
            return []
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            try:
                phase = "none"
                time_kw = {"start_time": start_time, "end_time": end_time}
                query_kw = {
                    **time_kw,
                    "limit": limit,
                    "user_id": user_id,
                    "l1_retrieval_scopes": l1_retrieval_scopes,
                }
                rows: list[tuple[Any, Any]] = []
                stemmed = ""
                if strict:
                    exact = build_exact_fts_query(escaped)
                    if exact:
                        rows = await self._run_bm25_query(db, exact, **query_kw)
                        if rows:
                            phase = "exact_and"
                if not rows:
                    stemmed = build_stemmed_fts_query(escaped)
                    if stemmed:
                        rows = await self._run_bm25_query(db, stemmed, **query_kw)
                        if rows:
                            phase = "stemmed_and"
                    else:
                        stemmed = ""
                if not rows:
                    rows = await self._run_bm25_query(db, escaped, **query_kw)
                    if rows:
                        phase = "original_and"
                if not strict:
                    if not rows:
                        for fallback_query in self._build_relaxed_fts_queries(query):
                            rows = await self._run_bm25_query(db, fallback_query, **query_kw)
                            if rows:
                                phase = "relaxed_phrase"
                                break
                    if not rows:
                        or_query = build_or_fts_query(escaped)
                        if or_query and or_query != escaped:
                            rows = await self._run_bm25_query(db, or_query, **query_kw)
                            if rows:
                                phase = "or_fallback"
                logger.info(
                    "BM25 search completed | phase=%s escaped=%r stemmed=%r "
                    "result_count=%d user_id=%s",
                    phase,
                    escaped,
                    stemmed,
                    len(rows),
                    user_id,
                )
                return [(str(row[0]), float(row[1])) for row in rows]
            except Exception as exc:
                logger.warning("FTS5 BM25 search failed: %s", exc)
                return []

    async def _run_bm25_query(
        self,
        db: aiosqlite.Connection,
        match_query: str,
        *,
        limit: int,
        user_id: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        l1_retrieval_scopes: list[str] | None = None,
    ) -> list[tuple[Any, Any]]:
        """Execute a single FTS5 BM25 query.

        When *user_id* is provided the FTS5 results are joined with
        ``fact_events`` so only events belonging to that user are ranked.
        When *start_time* / *end_time* are given, results are constrained
        to the timestamp range via ``fact_events.timestamp``.
        """
        if l1_retrieval_scopes is not None and not l1_retrieval_scopes:
            return []
        if (
            user_id
            or start_time is not None
            or end_time is not None
            or l1_retrieval_scopes is not None
        ):
            clauses = [
                "l1_events_fts MATCH ?",
                "fe.deleted_at IS NULL",
            ]
            params: list[Any] = [match_query]
            if user_id:
                clauses.append("fe.user_id = ?")
                params.append(user_id)
            if start_time is not None:
                clauses.append("fe.timestamp >= ?")
                params.append(start_time)
            if end_time is not None:
                clauses.append("fe.timestamp <= ?")
                params.append(end_time)
            if l1_retrieval_scopes is not None:
                placeholders = ", ".join("?" for _ in l1_retrieval_scopes)
                clauses.append(f"fe.l1_retrieval_scope IN ({placeholders})")
                params.extend(int(L1RetrievalScope.from_value(scope)) for scope in l1_retrieval_scopes)
            params.append(limit)
            where = " AND ".join(clauses)
            async with db.execute(
                f"""
                SELECT fts.event_id, bm25(l1_events_fts) AS score
                FROM l1_events_fts fts
                JOIN fact_events fe ON fe.event_id = fts.event_id
                WHERE {where}
                ORDER BY score
                LIMIT ?
                """,
                tuple(params),
            ) as cursor:
                return cast(list[tuple[Any, Any]], await cursor.fetchall())
        async with db.execute(
            """
            SELECT event_id, bm25(l1_events_fts) AS score
            FROM l1_events_fts
            WHERE l1_events_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (match_query, limit),
        ) as cursor:
            return cast(list[tuple[Any, Any]], await cursor.fetchall())

    def _build_relaxed_fts_queries(self, query: str) -> list[str]:
        """Build fallback FTS queries for punctuation-heavy comparison prompts."""
        relaxed_queries: list[str] = []
        phrase_queries: list[str] = []
        for match in re.finditer(r"""["']([^"']{3,})["']""", str(query or "")):
            escaped_phrase = escape_fts_query(tokenize_for_fts(match.group(1)))
            if escaped_phrase:
                phrase_queries.append(f'"{escaped_phrase}"')
        if phrase_queries:
            deduped = list(dict.fromkeys(phrase_queries))
            relaxed_queries.append(" OR ".join(deduped))
        return relaxed_queries

    async def backfill_fts(self, *, batch_size: int = 500) -> int:
        """Backfill the FTS5 index from existing fact_events rows.

        Returns the number of rows indexed.
        """
        host = cast(_L1EventFtsHostProtocol, self)
        await host.initialize()
        indexed = 0
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            async with db.execute(
                f"""
                SELECT event_id, content, author_type, content_type FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                AND event_id NOT IN (SELECT event_id FROM l1_events_fts)
                """
            ) as cursor:
                batch: list[tuple[str, str]] = []
                async for row in cursor:
                    event_id = str(row[0])
                    content = str(row[1] or "")
                    author_type = author_type_label(row[2])
                    content_type = content_type_label(row[3])
                    batch.append(
                        (
                            event_id,
                            tokenize_for_fts(
                                self._compose_search_text(content, author_type, content_type)
                            ),
                        )
                    )
                    if len(batch) >= batch_size:
                        await db.executemany(
                            "INSERT INTO l1_events_fts(event_id, content) VALUES (?, ?)",
                            batch,
                        )
                        indexed += len(batch)
                        batch.clear()
                if batch:
                    await db.executemany(
                        "INSERT INTO l1_events_fts(event_id, content) VALUES (?, ?)",
                        batch,
                    )
                    indexed += len(batch)
            await db.commit()
        return indexed

    def get_search_text(self, event: MemoryEvent) -> str:
        text = str(event.content or "").strip()
        retrieval_terms = build_l1_retrieval_terms_text(event)
        if retrieval_terms and retrieval_terms.lower() not in text.lower():
            text = f"{text} {retrieval_terms}".strip()
        return self._compose_search_text(text, event.author_type, event.content_type)

    @staticmethod
    def _compose_search_text(content: str, author_type: str, content_type: str) -> str:
        text = str(content or "").strip()
        labels = " ".join(
            part
            for part in (str(author_type or "").strip(), str(content_type or "").strip())
            if part
        )
        if text and labels:
            return f"{text} {labels}"
        return text or labels
