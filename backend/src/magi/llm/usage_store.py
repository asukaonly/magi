"""Persistence and aggregation for LLM usage metrics."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import aiosqlite

from ..core.logger import get_logger
from ..core.sqlite import sqlite_connection_async
from ..utils.runtime import get_runtime_paths

logger = get_logger(__name__)

_llm_usage_store: "LLMUsageStore | None" = None


class LLMUsageStore:
    """Record and query LLM usage statistics."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        runtime_paths = get_runtime_paths()
        self._db_path = Path(db_path or runtime_paths.llm_usage_db_path)

    async def initialize(self) -> None:
        """Ensure the usage table exists."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(str(self._db_path), profile="mixed") as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS llm_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    request_kind TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    usage_available INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    ttft_ms INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL DEFAULT 1,
                    error TEXT,
                    correlation_id TEXT,
                    session_id TEXT,
                    turn_id TEXT,
                    agent_id TEXT,
                    created_at REAL NOT NULL
                )
            """)
            await self._ensure_optional_columns(db)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at ON llm_usage(created_at)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_usage_provider_model ON llm_usage(provider, model)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_usage_request_kind ON llm_usage(request_kind)"
            )
            await db.commit()

    async def _ensure_optional_columns(self, db: aiosqlite.Connection) -> None:
        cursor = await db.execute("PRAGMA table_info(llm_usage)")
        rows = await cursor.fetchall()
        existing_columns = {str(row[1]) for row in rows}

        if "ttft_ms" not in existing_columns:
            await db.execute(
                "ALTER TABLE llm_usage ADD COLUMN ttft_ms INTEGER NOT NULL DEFAULT 0"
            )

        if "cost_usd" not in existing_columns:
            await db.execute(
                "ALTER TABLE llm_usage ADD COLUMN cost_usd REAL NOT NULL DEFAULT 0"
            )

    async def start(self) -> None:
        """Initialize storage. Subscription is wired by LLMUsageSubscriberModule."""
        await self.initialize()

    async def stop(self) -> None:
        """No-op. Subscription lifecycle is owned by LLMUsageSubscriberModule."""
        return

    async def record_call(self, payload: dict[str, Any]) -> None:
        """Persist a single normalized LLM usage event payload."""
        await self.initialize()
        async with sqlite_connection_async(str(self._db_path), profile="mixed") as db:
            await db.execute(
                """
                INSERT INTO llm_usage (
                    request_id,
                    provider,
                    model,
                    request_kind,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    usage_available,
                    latency_ms,
                    ttft_ms,
                    cost_usd,
                    success,
                    error,
                    correlation_id,
                    session_id,
                    turn_id,
                    agent_id,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(payload.get("request_id") or ""),
                    str(payload.get("provider") or "unknown"),
                    str(payload.get("model") or "unknown"),
                    str(payload.get("request_kind") or "unknown"),
                    int(payload.get("prompt_tokens") or 0),
                    int(payload.get("completion_tokens") or 0),
                    int(payload.get("total_tokens") or 0),
                    1 if payload.get("usage_available") else 0,
                    int(payload.get("latency_ms") or 0),
                    int(payload.get("ttft_ms") or 0),
                    float(payload.get("cost_usd") or 0),
                    1 if payload.get("success", True) else 0,
                    payload.get("error"),
                    payload.get("correlation_id"),
                    payload.get("session_id"),
                    payload.get("turn_id"),
                    payload.get("agent_id"),
                    float(payload.get("created_at") or time.time()),
                ),
            )
            await db.commit()

    async def get_summary(self, days: int = 7, model_limit: int = 8) -> dict[str, Any]:
        """Return aggregate LLM usage metrics for the requested window."""
        cutoff = time.time() - (days * 86400)
        await self.initialize()
        async with sqlite_connection_async(str(self._db_path), profile="mixed") as db:
            db.row_factory = aiosqlite.Row

            totals_cursor = await db.execute(
                """
                SELECT
                    COUNT(*) AS total_calls,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls,
                    SUM(CASE WHEN usage_available = 1 THEN 1 ELSE 0 END) AS calls_with_usage,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
                    COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0) AS avg_ttft_ms,
                    COALESCE(SUM(cost_usd), 0) AS total_cost_usd
                FROM llm_usage
                WHERE created_at >= ?
                """,
                (cutoff,),
            )
            totals = await totals_cursor.fetchone()

            providers = await self._fetch_grouped_usage(
                db,
                """
                SELECT
                    provider,
                    COUNT(*) AS calls,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
                    COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0) AS avg_ttft_ms,
                    COALESCE(SUM(cost_usd), 0) AS cost_usd
                FROM llm_usage
                WHERE created_at >= ?
                GROUP BY provider
                ORDER BY total_tokens DESC, calls DESC
                """,
                (cutoff,),
            )

            models = await self._fetch_grouped_usage(
                db,
                """
                SELECT
                    provider,
                    model,
                    COUNT(*) AS calls,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
                    COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0) AS avg_ttft_ms,
                    COALESCE(SUM(cost_usd), 0) AS cost_usd
                FROM llm_usage
                WHERE created_at >= ?
                GROUP BY provider, model
                ORDER BY total_tokens DESC, calls DESC
                LIMIT ?
                """,
                (cutoff, model_limit),
            )

            request_kinds = await self._fetch_grouped_usage(
                db,
                """
                SELECT
                    request_kind,
                    COUNT(*) AS calls,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
                    COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0) AS avg_ttft_ms,
                    COALESCE(SUM(cost_usd), 0) AS cost_usd
                FROM llm_usage
                WHERE created_at >= ?
                GROUP BY request_kind
                ORDER BY total_tokens DESC, calls DESC
                """,
                (cutoff,),
            )

        total_calls = int(totals["total_calls"] or 0)
        successful_calls = int(totals["successful_calls"] or 0)
        failed_calls = int(totals["failed_calls"] or 0)
        return {
            "window_days": days,
            "totals": {
                "total_calls": total_calls,
                "successful_calls": successful_calls,
                "failed_calls": failed_calls if failed_calls >= 0 else max(total_calls - successful_calls, 0),
                "calls_with_usage": int(totals["calls_with_usage"] or 0),
                "prompt_tokens": int(totals["prompt_tokens"] or 0),
                "completion_tokens": int(totals["completion_tokens"] or 0),
                "total_tokens": int(totals["total_tokens"] or 0),
                "avg_latency_ms": round(float(totals["avg_latency_ms"] or 0), 2),
                "avg_ttft_ms": round(float(totals["avg_ttft_ms"] or 0), 2) if float(totals["avg_ttft_ms"] or 0) > 0 else None,
                "total_cost_usd": round(float(totals["total_cost_usd"] or 0), 4),
            },
            "providers": providers,
            "models": models,
            "request_kinds": request_kinds,
        }

    async def get_timeseries(self, days: int = 7) -> list[dict[str, Any]]:
        """Return daily token usage trend for the requested window."""
        cutoff = time.time() - (days * 86400)
        await self.initialize()
        async with sqlite_connection_async(str(self._db_path), profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT
                    strftime('%Y-%m-%d', datetime(created_at, 'unixepoch', 'localtime')) AS day,
                    COUNT(*) AS calls,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(cost_usd), 0) AS cost_usd
                FROM llm_usage
                WHERE created_at >= ?
                GROUP BY day
                ORDER BY day ASC
                """,
                (cutoff,),
            )
            rows = await cursor.fetchall()

        return [
            {
                "day": str(row["day"]),
                "calls": int(row["calls"] or 0),
                "prompt_tokens": int(row["prompt_tokens"] or 0),
                "completion_tokens": int(row["completion_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "cost_usd": round(float(row["cost_usd"] or 0), 4),
            }
            for row in rows
        ]

    async def _fetch_grouped_usage(
        self,
        db: aiosqlite.Connection,
        query: str,
        params: tuple[Any, ...],
    ) -> list[dict[str, Any]]:
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]


def get_llm_usage_store() -> LLMUsageStore:
    """Get the shared LLM usage store instance."""
    global _llm_usage_store
    if _llm_usage_store is None:
        _llm_usage_store = LLMUsageStore()
    return _llm_usage_store


def set_llm_usage_store(store: LLMUsageStore | None) -> None:
    """Set the shared LLM usage store instance."""
    global _llm_usage_store
    _llm_usage_store = store
