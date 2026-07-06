"""Read, search, and maintenance operations for L4 procedural memory."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...sql_search import build_like_search_clause
from ...hybrid_retrieval.fts_utils import escape_fts_query, tokenize_for_fts
from ..advisory.tools import build_tool_advisory, is_tool_advisory_notable
from ..storage.schema import EXECUTION_TRACES_TABLE, SKILL_CHUNKS_TABLE
from ..storage.serialization import row_to_execution_trace_dict, row_to_skill_dict
from .search import (
    escaped_skill_like_pattern,
    fts_backfill_row,
    ids_from_rows,
    ordered_skill_dicts_from_rows,
    plain_skill_like_pattern,
    rows_to_bm25_pairs,
)

logger = logging.getLogger(__name__)


class L4ProceduralRetrievalMixin:
    """Public read/search surface for procedural skills and execution traces."""

    db_path: str
    _vector_index: Any | None

    async def initialize(self) -> None:
        raise NotImplementedError

    async def _semantic_query_strategies(self, *, query: str, limit: int) -> List[Dict[str, Any]]:
        raise NotImplementedError

    async def get_skill(self, *, skill_name: str, skill_category: str) -> Dict[str, Any] | None:
        """Fetch a single procedural skill."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM procedural_skills WHERE skill_name = ? AND skill_category = ? AND deleted_at IS NULL",
                (skill_name, skill_category),
            ) as cursor:
                row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def count_skills(self, *, query: str | None = None) -> int:
        """Count all procedural skills."""
        await self.initialize()
        sql = "SELECT COUNT(*) FROM procedural_skills WHERE deleted_at IS NULL"
        args: list[Any] = []
        search_sql, search_args = build_like_search_clause(
            [
                "skill_id",
                "skill_name",
                "skill_category",
                "skill_type",
                "circuit_breaker_state",
                "optimized_prompt",
                "optimized_params",
                "context_affinity",
                "source_event_ids",
            ],
            query,
        )
        sql += search_sql
        args.extend(search_args)
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(sql, tuple(args)) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def get_all_skills(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        query: str | None = None,
    ) -> List[Dict[str, Any]]:
        """List all stored skills."""
        await self.initialize()
        sql = "SELECT * FROM procedural_skills WHERE deleted_at IS NULL"
        args: list[Any] = []
        search_sql, search_args = build_like_search_clause(
            [
                "skill_id",
                "skill_name",
                "skill_category",
                "skill_type",
                "circuit_breaker_state",
                "optimized_prompt",
                "optimized_params",
                "context_affinity",
                "source_event_ids",
            ],
            query,
        )
        sql += search_sql
        args.extend(search_args)
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        args.extend([int(limit), int(offset)])
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def get_tool_advisory(
        self,
        tool_names: List[str],
        task_context: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Return lightweight advisory for each requested tool."""
        if not tool_names:
            return []
        await self.initialize()
        placeholders = ", ".join("?" for _ in tool_names)
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT skill_name, circuit_breaker_state, success_rate,
                       total_attempts, optimized_prompt, context_affinity,
                       failure_count, last_failure_at
                FROM procedural_skills
                WHERE skill_category = 'tool' AND skill_name IN ({placeholders}) AND deleted_at IS NULL
                """,
                tuple(tool_names),
            ) as cursor:
                rows = await cursor.fetchall()

        known = {str(row["skill_name"]): row for row in rows}
        result: List[Dict[str, Any]] = []

        for name in tool_names:
            row = known.get(name)
            if row is None:
                continue
            result.append(
                build_tool_advisory(row=row, tool_name=name, task_context=task_context)
            )

        return result

    async def get_notable_advisories(
        self,
        task_context: str | None = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Return advisories for tools with actionable status."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT skill_name, circuit_breaker_state, success_rate,
                       total_attempts, optimized_prompt, context_affinity,
                       failure_count, last_failure_at
                FROM procedural_skills
                WHERE skill_category = 'tool'
                  AND deleted_at IS NULL
                  AND (
                      circuit_breaker_state != 'closed'
                      OR (optimized_prompt IS NOT NULL AND optimized_prompt != '' AND optimized_prompt != '{}')
                      OR (success_rate < 0.7 AND total_attempts >= 3)
                  )
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (int(limit * 2),),
            ) as cursor:
                rows = await cursor.fetchall()

        result: List[Dict[str, Any]] = []
        for row in rows:
            advisory = build_tool_advisory(
                row=row,
                tool_name=str(row["skill_name"]),
                task_context=task_context,
            )
            if not is_tool_advisory_notable(advisory):
                continue

            result.append(advisory)
            if len(result) >= limit:
                break
        return result

    async def query_strategies(self, *, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search procedural skills by sqlite-vec and fall back to SQL LIKE."""
        await self.initialize()
        semantic = await self._semantic_query_strategies(query=query, limit=limit)
        if semantic:
            return semantic
        like_query = plain_skill_like_pattern(query)
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM procedural_skills
                WHERE (skill_name LIKE ? OR COALESCE(optimized_prompt, '') LIKE ?)
                  AND deleted_at IS NULL
                ORDER BY success_rate DESC, updated_at DESC
                LIMIT ?
                """,
                (like_query, like_query, int(limit)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def clear(self) -> int:
        """Delete all procedural skills."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM procedural_skills") as cursor:
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
            await db.execute("DELETE FROM procedural_skills")
            await db.execute(f"DELETE FROM {SKILL_CHUNKS_TABLE}")
            await db.execute(f"DELETE FROM {EXECUTION_TRACES_TABLE}")
            await db.execute("DELETE FROM l4_skills_fts")
            await db.commit()
        if self._vector_index is not None:
            await self._vector_index.clear()
        return count

    async def bm25_search(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> List[Tuple[str, float]]:
        """Search L4 skills via FTS5 BM25 ranking."""
        await self.initialize()
        tokenized = tokenize_for_fts(query)
        if not tokenized:
            return []
        escaped = escape_fts_query(tokenized)
        if not escaped:
            return []
        async with sqlite_connection_async(self.db_path) as db:
            try:
                async with db.execute(
                    """
                    SELECT skill_id, bm25(l4_skills_fts) AS score
                    FROM l4_skills_fts
                    WHERE l4_skills_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (escaped, limit),
                ) as cursor:
                    rows = await cursor.fetchall()
                return rows_to_bm25_pairs(rows)
            except Exception as exc:
                logger.warning("FTS5 BM25 search failed for L4 skills: %s", exc)
                return []

    async def keyword_search(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> List[str]:
        """Return skill IDs matching *query* via LIKE keyword search."""
        like_q = escaped_skill_like_pattern(query)
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT skill_id FROM procedural_skills
                WHERE (skill_name LIKE ? ESCAPE '\\' OR COALESCE(optimized_prompt, '') LIKE ? ESCAPE '\\')
                  AND deleted_at IS NULL
                ORDER BY success_rate DESC, updated_at DESC
                LIMIT ?
                """,
                (like_q, like_q, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return ids_from_rows(rows)

    async def fetch_by_ids(self, skill_ids: List[str]) -> List[Dict[str, Any]]:
        """Fetch full skill records by IDs, preserving input order."""
        if not skill_ids:
            return []
        placeholders = ", ".join("?" for _ in skill_ids)
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM procedural_skills WHERE skill_id IN ({placeholders}) AND deleted_at IS NULL",
                tuple(skill_ids),
            ) as cursor:
                rows = await cursor.fetchall()
        return ordered_skill_dicts_from_rows(rows=rows, skill_ids=skill_ids)

    async def backfill_fts(self, *, batch_size: int = 500) -> int:
        """Backfill FTS5 index from existing procedural_skills rows."""
        await self.initialize()
        indexed = 0
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT skill_id, skill_name, skill_category, optimized_prompt
                FROM procedural_skills
                WHERE skill_id NOT IN (SELECT skill_id FROM l4_skills_fts)
                """
            ) as cursor:
                batch: list[tuple[str, str]] = []
                async for row in cursor:
                    batch.append(fts_backfill_row(row))
                    if len(batch) >= batch_size:
                        await db.executemany(
                            "INSERT INTO l4_skills_fts(skill_id, content) VALUES (?, ?)",
                            batch,
                        )
                        indexed += len(batch)
                        batch.clear()
                if batch:
                    await db.executemany(
                        "INSERT INTO l4_skills_fts(skill_id, content) VALUES (?, ?)",
                        batch,
                    )
                    indexed += len(batch)
            await db.commit()
        return indexed

    async def get_recent_traces(
        self,
        skill_id: str,
        *,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Return the most recent execution traces for a skill."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT trace_id, skill_id, event_id, turn_id, success, duration_ms,
                       error_summary, input_summary, output_summary, task_context,
                       created_at
                FROM {EXECUTION_TRACES_TABLE}
                WHERE skill_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (skill_id, int(limit)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [row_to_execution_trace_dict(row) for row in rows]

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return row_to_skill_dict(row)


__all__ = ["L4ProceduralRetrievalMixin"]
