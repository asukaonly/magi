"""Persistence and aggregation for LLM usage metrics."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

from ..core.logger import get_logger
from ..core.operation_barrier import AsyncOperationBarrier
from ..core.sqlite import sqlite_connection_async
from ..utils.runtime import get_runtime_paths

logger = get_logger(__name__)

_llm_usage_store: "LLMUsageStore | None" = None

_SUMMARY_TOTALS_SQL = """
SELECT
    COUNT(*) AS total_calls,
    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls,
    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls,
    SUM(CASE WHEN usage_available = 1 THEN 1 ELSE 0 END) AS calls_with_usage,
    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
    COALESCE(SUM(total_tokens), 0) AS total_tokens,
    COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
    COALESCE(SUM(cache_write_1h_tokens), 0) AS cache_write_1h_tokens,
    CASE
        WHEN COALESCE(SUM(prompt_tokens), 0) > 0
        THEN ROUND(COALESCE(SUM(cache_read_tokens), 0) * 100.0 / SUM(prompt_tokens), 2)
        ELSE 0
    END AS cache_hit_rate,
    COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
    COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0) AS avg_ttft_ms,
    COALESCE(SUM(cost_usd), 0) AS total_cost_usd
FROM llm_usage
WHERE created_at >= ?
"""

_SUMMARY_PROVIDERS_SQL = """
SELECT
    provider,
    COUNT(*) AS calls,
    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls,
    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls,
    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
    COALESCE(SUM(total_tokens), 0) AS total_tokens,
    COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
    COALESCE(SUM(cache_write_1h_tokens), 0) AS cache_write_1h_tokens,
    CASE
        WHEN COALESCE(SUM(prompt_tokens), 0) > 0
        THEN ROUND(COALESCE(SUM(cache_read_tokens), 0) * 100.0 / SUM(prompt_tokens), 2)
        ELSE 0
    END AS cache_hit_rate,
    COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
    COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0) AS avg_ttft_ms,
    COALESCE(SUM(cost_usd), 0) AS cost_usd,
    MAX(cost_currency) AS cost_currency
FROM llm_usage
WHERE created_at >= ?
GROUP BY provider
ORDER BY total_tokens DESC, calls DESC
"""

_SUMMARY_MODELS_SQL = """
SELECT
    provider,
    model,
    COUNT(*) AS calls,
    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls,
    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls,
    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
    COALESCE(SUM(total_tokens), 0) AS total_tokens,
    COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
    COALESCE(SUM(cache_write_1h_tokens), 0) AS cache_write_1h_tokens,
    CASE
        WHEN COALESCE(SUM(prompt_tokens), 0) > 0
        THEN ROUND(COALESCE(SUM(cache_read_tokens), 0) * 100.0 / SUM(prompt_tokens), 2)
        ELSE 0
    END AS cache_hit_rate,
    COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
    COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0) AS avg_ttft_ms,
    COALESCE(SUM(cost_usd), 0) AS cost_usd,
    MAX(cost_currency) AS cost_currency
FROM llm_usage
WHERE created_at >= ?
GROUP BY provider, model
ORDER BY total_tokens DESC, calls DESC
LIMIT ?
"""

_SUMMARY_REQUEST_KINDS_SQL = """
SELECT
    request_kind,
    COUNT(*) AS calls,
    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls,
    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls,
    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
    COALESCE(SUM(total_tokens), 0) AS total_tokens,
    COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
    COALESCE(SUM(cache_write_1h_tokens), 0) AS cache_write_1h_tokens,
    CASE
        WHEN COALESCE(SUM(prompt_tokens), 0) > 0
        THEN ROUND(COALESCE(SUM(cache_read_tokens), 0) * 100.0 / SUM(prompt_tokens), 2)
        ELSE 0
    END AS cache_hit_rate,
    COALESCE(AVG(latency_ms), 0) AS avg_latency_ms,
    COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0) AS avg_ttft_ms,
    COALESCE(SUM(cost_usd), 0) AS cost_usd,
    MAX(cost_currency) AS cost_currency
FROM llm_usage
WHERE created_at >= ?
GROUP BY request_kind
ORDER BY total_tokens DESC, calls DESC
"""

_SUMMARY_COST_BY_CURRENCY_SQL = """
SELECT cost_currency AS currency, COALESCE(SUM(cost_usd), 0) AS amount
FROM llm_usage
WHERE created_at >= ? AND cost_currency IS NOT NULL
GROUP BY cost_currency
ORDER BY amount DESC
"""

_INSERT_CACHE_OBSERVATION_SQL = """
INSERT INTO llm_cache_observations (
    request_id,
    provider,
    model,
    request_kind,
    session_id,
    turn_id,
    agent_id,
    cache_strategy,
    cache_eligible,
    system_head_hash,
    system_head_chars,
    turn_context_hash,
    turn_context_chars,
    tools_hash,
    tool_count,
    tool_names_json,
    system_head_reused,
    tools_reused,
    predicted_miss_reasons_json,
    cache_fields_seen,
    cache_read_tokens,
    cache_write_tokens,
    cache_write_1h_tokens,
    created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


@dataclass(slots=True)
class _CacheObservationContext:
    created_at: float
    provider: str
    model: str
    request_kind: str
    session_id: Any
    system_head_hash: str
    tools_hash: str


@dataclass(slots=True)
class _CacheObservationReuse:
    system_head_reused: bool | None
    tools_reused: bool | None
    miss_reasons: list[str]


class LLMUsageStore:
    """Record and query LLM usage statistics."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        runtime_paths = get_runtime_paths()
        self._db_path = Path(db_path or runtime_paths.llm_usage_db_path)
        self._user_content_barrier = AsyncOperationBarrier()

    async def initialize(self) -> None:
        """Ensure parent directory exists; schema is alembic-managed."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    async def start(self) -> None:
        """Initialize storage. Subscription is wired by LLMUsageSubscriberModule."""
        await self.initialize()

    async def stop(self) -> None:
        """No-op. Subscription lifecycle is owned by LLMUsageSubscriberModule."""
        return

    @asynccontextmanager
    async def user_content_operation(self) -> AsyncIterator[None]:
        """Join the shared boundary used by writes, retention, and full clear."""
        async with self._user_content_barrier.operation():
            yield

    async def clear_user_content(self) -> int:
        """Erase raw usage, cache diagnostics, and retained usage rollups."""
        await self.initialize()
        async with self._user_content_barrier.exclusive():
            async with sqlite_connection_async(
                str(self._db_path),
                profile="mixed",
            ) as db:
                await db.execute("PRAGMA secure_delete=ON")
                await db.execute("BEGIN IMMEDIATE")
                try:
                    deleted = 0
                    for table_name in (
                        "llm_cache_observations",
                        "llm_usage_rollups",
                        "llm_usage",
                    ):
                        cursor = await db.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (table_name,),
                        )
                        if await cursor.fetchone() is None:
                            continue
                        cursor = await db.execute(f"SELECT COUNT(*) FROM {table_name}")
                        row = await cursor.fetchone()
                        deleted += int(row[0] or 0)
                        await db.execute(f"DELETE FROM {table_name}")
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
                await db.execute("VACUUM")
                await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return deleted

    async def record_call(self, payload: dict[str, Any]) -> None:
        """Persist a single normalized LLM usage event payload."""
        async with self.user_content_operation():
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
                        cache_read_tokens,
                        cache_write_tokens,
                        cache_write_1h_tokens,
                        usage_available,
                        latency_ms,
                        ttft_ms,
                        cost_usd,
                        cost_currency,
                        success,
                        error,
                        correlation_id,
                        session_id,
                        turn_id,
                        agent_id,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(payload.get("request_id") or ""),
                        str(payload.get("provider") or "unknown"),
                        str(payload.get("model") or "unknown"),
                        str(payload.get("request_kind") or "unknown"),
                        int(payload.get("prompt_tokens") or 0),
                        int(payload.get("completion_tokens") or 0),
                        int(payload.get("total_tokens") or 0),
                        int(payload.get("cache_read_tokens") or 0),
                        int(payload.get("cache_write_tokens") or 0),
                        int(payload.get("cache_write_1h_tokens") or 0),
                        1 if payload.get("usage_available") else 0,
                        int(payload.get("latency_ms") or 0),
                        int(payload.get("ttft_ms") or 0),
                        # cost_usd holds the amount in cost_currency (historically USD-only);
                        # NULL currency is the "no pricing data" sentinel.
                        float(payload.get("cost_usd") or 0),
                        payload.get("cost_currency"),
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

    async def record_cache_observation(self, payload: dict[str, Any]) -> None:
        """Persist lightweight prompt-cache diagnostics for one LLM call."""
        async with self.user_content_operation():
            await self.initialize()
            context = self._cache_observation_context(payload)
            async with sqlite_connection_async(str(self._db_path), profile="mixed") as db:
                db.row_factory = aiosqlite.Row
                previous = await self._fetch_previous_cache_observation(
                    db,
                    provider=context.provider,
                    model=context.model,
                    request_kind=context.request_kind,
                    session_id=context.session_id,
                    created_at=context.created_at,
                )
                reuse = self._cache_observation_reuse(payload, context, previous)
                await self._insert_cache_observation(db, payload, context, reuse)
                await db.commit()

    def _cache_observation_context(
        self,
        payload: dict[str, Any],
    ) -> _CacheObservationContext:
        return _CacheObservationContext(
            created_at=float(payload.get("created_at") or time.time()),
            provider=str(payload.get("provider") or "unknown"),
            model=str(payload.get("model") or "unknown"),
            request_kind=str(payload.get("request_kind") or "unknown"),
            session_id=payload.get("session_id"),
            system_head_hash=str(payload.get("system_head_hash") or ""),
            tools_hash=str(payload.get("tools_hash") or ""),
        )

    def _cache_observation_reuse(
        self,
        payload: dict[str, Any],
        context: _CacheObservationContext,
        previous: aiosqlite.Row | None,
    ) -> _CacheObservationReuse:
        system_head_reused: bool | None = None
        tools_reused: bool | None = None
        miss_reasons: list[str] = []
        if previous is None:
            miss_reasons.append("first_observed_call")
        else:
            system_head_reused = str(previous["system_head_hash"] or "") == context.system_head_hash
            tools_reused = str(previous["tools_hash"] or "") == context.tools_hash
            if not system_head_reused:
                miss_reasons.append("system_head_changed")
            if not tools_reused:
                miss_reasons.append("tools_changed")
            if not miss_reasons:
                miss_reasons.append("prefix_stable")
        if not bool(payload.get("cache_eligible")):
            miss_reasons = ["cache_not_eligible"]
        return _CacheObservationReuse(
            system_head_reused=system_head_reused,
            tools_reused=tools_reused,
            miss_reasons=miss_reasons,
        )

    async def _insert_cache_observation(
        self,
        db: aiosqlite.Connection,
        payload: dict[str, Any],
        context: _CacheObservationContext,
        reuse: _CacheObservationReuse,
    ) -> None:
        await db.execute(
            _INSERT_CACHE_OBSERVATION_SQL,
            self._cache_observation_insert_values(payload, context, reuse),
        )

    def _cache_observation_insert_values(
        self,
        payload: dict[str, Any],
        context: _CacheObservationContext,
        reuse: _CacheObservationReuse,
    ) -> tuple[Any, ...]:
        return (
            str(payload.get("request_id") or ""),
            context.provider,
            context.model,
            context.request_kind,
            context.session_id,
            payload.get("turn_id"),
            payload.get("agent_id"),
            str(payload.get("cache_strategy") or "none"),
            1 if payload.get("cache_eligible") else 0,
            context.system_head_hash,
            int(payload.get("system_head_chars") or 0),
            str(payload.get("turn_context_hash") or ""),
            int(payload.get("turn_context_chars") or 0),
            context.tools_hash,
            int(payload.get("tool_count") or 0),
            json.dumps(list(payload.get("tool_names") or []), ensure_ascii=False),
            self._bool_to_nullable_int(reuse.system_head_reused),
            self._bool_to_nullable_int(reuse.tools_reused),
            json.dumps(reuse.miss_reasons, ensure_ascii=False),
            1 if payload.get("cache_fields_seen") else 0,
            int(payload.get("cache_read_tokens") or 0),
            int(payload.get("cache_write_tokens") or 0),
            int(payload.get("cache_write_1h_tokens") or 0),
            context.created_at,
        )

    async def list_cache_observations(
        self,
        *,
        days: int = 7,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return recent prompt-cache diagnostic rows."""
        cutoff = time.time() - (days * 86400)
        await self.initialize()
        async with sqlite_connection_async(str(self._db_path), profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT *
                FROM llm_cache_observations
                WHERE created_at >= ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (cutoff, max(1, int(limit))),
            )
            rows = await cursor.fetchall()
        return [self._cache_observation_row_to_dict(row) for row in rows]

    async def get_summary(self, days: int = 7, model_limit: int = 8) -> dict[str, Any]:
        """Return aggregate LLM usage metrics for the requested window."""
        cutoff = time.time() - (days * 86400)
        await self.initialize()
        async with sqlite_connection_async(str(self._db_path), profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            totals = await self._fetch_summary_totals(db, cutoff)
            providers = await self._fetch_grouped_usage(db, _SUMMARY_PROVIDERS_SQL, (cutoff,))
            models = await self._fetch_grouped_usage(db, _SUMMARY_MODELS_SQL, (cutoff, model_limit))
            request_kinds = await self._fetch_grouped_usage(
                db, _SUMMARY_REQUEST_KINDS_SQL, (cutoff,)
            )
            cost_by_currency = await self._fetch_cost_by_currency(db, cutoff)

        return self._build_summary_response(
            days=days,
            totals=totals,
            providers=providers,
            models=models,
            request_kinds=request_kinds,
            cost_by_currency=cost_by_currency,
        )

    async def _fetch_summary_totals(
        self,
        db: aiosqlite.Connection,
        cutoff: float,
    ) -> aiosqlite.Row:
        cursor = await db.execute(_SUMMARY_TOTALS_SQL, (cutoff,))
        return await cursor.fetchone()

    async def _fetch_cost_by_currency(
        self,
        db: aiosqlite.Connection,
        cutoff: float,
    ) -> list[dict[str, Any]]:
        cursor = await db.execute(_SUMMARY_COST_BY_CURRENCY_SQL, (cutoff,))
        rows = await cursor.fetchall()
        return [
            {"currency": str(row["currency"]), "amount": round(float(row["amount"] or 0), 4)}
            for row in rows
        ]

    @staticmethod
    def _build_summary_response(
        *,
        days: int,
        totals: aiosqlite.Row,
        providers: list[dict[str, Any]],
        models: list[dict[str, Any]],
        request_kinds: list[dict[str, Any]],
        cost_by_currency: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total_calls = int(totals["total_calls"] or 0)
        successful_calls = int(totals["successful_calls"] or 0)
        failed_calls = int(totals["failed_calls"] or 0)
        avg_ttft_ms = float(totals["avg_ttft_ms"] or 0)
        return {
            "window_days": days,
            "totals": {
                "total_calls": total_calls,
                "successful_calls": successful_calls,
                "failed_calls": (
                    failed_calls if failed_calls >= 0 else max(total_calls - successful_calls, 0)
                ),
                "calls_with_usage": int(totals["calls_with_usage"] or 0),
                "prompt_tokens": int(totals["prompt_tokens"] or 0),
                "completion_tokens": int(totals["completion_tokens"] or 0),
                "total_tokens": int(totals["total_tokens"] or 0),
                "cache_read_tokens": int(totals["cache_read_tokens"] or 0),
                "cache_write_tokens": int(totals["cache_write_tokens"] or 0),
                "cache_write_1h_tokens": int(totals["cache_write_1h_tokens"] or 0),
                "cache_hit_rate": round(float(totals["cache_hit_rate"] or 0), 2),
                "avg_latency_ms": round(float(totals["avg_latency_ms"] or 0), 2),
                "avg_ttft_ms": round(avg_ttft_ms, 2) if avg_ttft_ms > 0 else None,
                "total_cost_usd": round(float(totals["total_cost_usd"] or 0), 4),
                "cost_by_currency": cost_by_currency,
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
                    COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
                    COALESCE(SUM(cache_write_1h_tokens), 0) AS cache_write_1h_tokens,
                    CASE
                        WHEN COALESCE(SUM(prompt_tokens), 0) > 0
                        THEN ROUND(COALESCE(SUM(cache_read_tokens), 0) * 100.0 / SUM(prompt_tokens), 2)
                        ELSE 0
                    END AS cache_hit_rate,
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
                "cache_read_tokens": int(row["cache_read_tokens"] or 0),
                "cache_write_tokens": int(row["cache_write_tokens"] or 0),
                "cache_write_1h_tokens": int(row["cache_write_1h_tokens"] or 0),
                "cache_hit_rate": round(float(row["cache_hit_rate"] or 0), 2),
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

    async def _fetch_previous_cache_observation(
        self,
        db: aiosqlite.Connection,
        *,
        provider: str,
        model: str,
        request_kind: str,
        session_id: Any,
        created_at: float,
    ) -> aiosqlite.Row | None:
        if not session_id:
            return None
        cursor = await db.execute(
            """
            SELECT system_head_hash, tools_hash
            FROM llm_cache_observations
            WHERE session_id = ?
              AND provider = ?
              AND model = ?
              AND request_kind = ?
              AND created_at <= ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (session_id, provider, model, request_kind, created_at),
        )
        return await cursor.fetchone()

    @staticmethod
    def _bool_to_nullable_int(value: bool | None) -> int | None:
        if value is None:
            return None
        return 1 if value else 0

    @classmethod
    def _cache_observation_row_to_dict(cls, row: aiosqlite.Row) -> dict[str, Any]:
        data = {key: row[key] for key in row.keys()}
        data["cache_eligible"] = bool(data.get("cache_eligible"))
        data["cache_fields_seen"] = bool(data.get("cache_fields_seen"))
        data["system_head_reused"] = cls._nullable_int_to_bool(data.get("system_head_reused"))
        data["tools_reused"] = cls._nullable_int_to_bool(data.get("tools_reused"))
        data["tool_names"] = cls._loads_json_list(data.pop("tool_names_json", "[]"))
        data["predicted_miss_reasons"] = cls._loads_json_list(
            data.pop("predicted_miss_reasons_json", "[]")
        )
        return data

    @staticmethod
    def _nullable_int_to_bool(value: Any) -> bool | None:
        if value is None:
            return None
        return bool(value)

    @staticmethod
    def _loads_json_list(value: Any) -> list[Any]:
        try:
            parsed = json.loads(str(value or "[]"))
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []


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
