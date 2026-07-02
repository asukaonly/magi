"""FTS5 and BM25 helpers for the canonical L1 event store."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _Bm25SearchOptions:
    limit: int
    user_id: str | None
    start_time: float | None
    end_time: float | None
    strict: bool
    l1_retrieval_scopes: list[str] | None


@dataclass(frozen=True)
class _Bm25PhaseResult:
    phase: str
    rows: list[tuple[Any, Any]]
    stemmed: str = ""


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
        escaped = self._prepare_bm25_query(query)
        if not escaped:
            return []
        options = _Bm25SearchOptions(
            limit=limit,
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            strict=strict,
            l1_retrieval_scopes=l1_retrieval_scopes,
        )
        async with sqlite_connection_async(host.db_path, profile="hot_write") as db:
            try:
                result = await self._run_bm25_search_phases(
                    db,
                    query=query,
                    escaped=escaped,
                    options=options,
                )
                self._log_bm25_result(result, escaped=escaped, user_id=user_id)
                return self._format_bm25_rows(result.rows)
            except Exception as exc:
                logger.warning("FTS5 BM25 search failed: %s", exc)
                return []

    @staticmethod
    def _prepare_bm25_query(query: str) -> str:
        tokenized = tokenize_for_fts(query)
        if not tokenized:
            return ""
        return cast(str, escape_fts_query(tokenized))

    async def _run_bm25_search_phases(
        self,
        db: aiosqlite.Connection,
        *,
        query: str,
        escaped: str,
        options: _Bm25SearchOptions,
    ) -> _Bm25PhaseResult:
        required = await self._run_required_bm25_phases(
            db,
            escaped=escaped,
            options=options,
        )
        if required.rows or options.strict:
            return required
        relaxed = await self._run_relaxed_bm25_phases(
            db,
            query=query,
            escaped=escaped,
            options=options,
        )
        if relaxed.rows:
            return _Bm25PhaseResult(relaxed.phase, relaxed.rows, stemmed=required.stemmed)
        return required

    async def _run_required_bm25_phases(
        self,
        db: aiosqlite.Connection,
        *,
        escaped: str,
        options: _Bm25SearchOptions,
    ) -> _Bm25PhaseResult:
        if options.strict:
            exact = build_exact_fts_query(escaped)
            rows = await self._run_bm25_query_with_options(db, exact, options=options)
            if rows:
                return _Bm25PhaseResult("exact_and", rows)

        stemmed = build_stemmed_fts_query(escaped) or ""
        if stemmed:
            rows = await self._run_bm25_query_with_options(db, stemmed, options=options)
            if rows:
                return _Bm25PhaseResult("stemmed_and", rows, stemmed=stemmed)

        rows = await self._run_bm25_query_with_options(db, escaped, options=options)
        if rows:
            return _Bm25PhaseResult("original_and", rows, stemmed=stemmed)
        return _Bm25PhaseResult("none", [], stemmed=stemmed)

    async def _run_relaxed_bm25_phases(
        self,
        db: aiosqlite.Connection,
        *,
        query: str,
        escaped: str,
        options: _Bm25SearchOptions,
    ) -> _Bm25PhaseResult:
        for fallback_query in self._build_relaxed_fts_queries(query):
            rows = await self._run_bm25_query_with_options(db, fallback_query, options=options)
            if rows:
                return _Bm25PhaseResult("relaxed_phrase", rows)

        or_query = build_or_fts_query(escaped)
        if or_query and or_query != escaped:
            rows = await self._run_bm25_query_with_options(db, or_query, options=options)
            if rows:
                return _Bm25PhaseResult("or_fallback", rows)
        return _Bm25PhaseResult("none", [])

    async def _run_bm25_query_with_options(
        self,
        db: aiosqlite.Connection,
        match_query: str,
        *,
        options: _Bm25SearchOptions,
    ) -> list[tuple[Any, Any]]:
        if not match_query:
            return []
        return await self._run_bm25_query(
            db,
            match_query,
            limit=options.limit,
            user_id=options.user_id,
            start_time=options.start_time,
            end_time=options.end_time,
            l1_retrieval_scopes=options.l1_retrieval_scopes,
        )

    @staticmethod
    def _format_bm25_rows(rows: list[tuple[Any, Any]]) -> List[Tuple[str, float]]:
        return [(str(row[0]), float(row[1])) for row in rows]

    @staticmethod
    def _log_bm25_result(
        result: _Bm25PhaseResult,
        *,
        escaped: str,
        user_id: str | None,
    ) -> None:
        logger.info(
            "BM25 search completed | phase=%s escaped=%r stemmed=%r " "result_count=%d user_id=%s",
            result.phase,
            escaped,
            result.stemmed,
            len(result.rows),
            user_id,
        )

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
                params.extend(
                    int(L1RetrievalScope.from_value(scope)) for scope in l1_retrieval_scopes
                )
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
            async with db.execute(f"""
                SELECT event_id, content, author_type, content_type FROM {FACT_EVENTS_TABLE}
                WHERE deleted_at IS NULL
                AND event_id NOT IN (SELECT event_id FROM l1_events_fts)
                """) as cursor:
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
