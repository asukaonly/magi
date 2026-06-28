"""Persistence and aggregation for LLM usage metrics."""
from __future__ import annotations

import json
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
        """Ensure parent directory exists; schema is alembic-managed."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

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
        await self.initialize()
        created_at = float(payload.get("created_at") or time.time())
        provider = str(payload.get("provider") or "unknown")
        model = str(payload.get("model") or "unknown")
        request_kind = str(payload.get("request_kind") or "unknown")
        session_id = payload.get("session_id")
        system_head_hash = str(payload.get("system_head_hash") or "")
        tools_hash = str(payload.get("tools_hash") or "")

        async with sqlite_connection_async(str(self._db_path), profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            previous = await self._fetch_previous_cache_observation(
                db,
                provider=provider,
                model=model,
                request_kind=request_kind,
                session_id=session_id,
                created_at=created_at,
            )
            system_head_reused: bool | None = None
            tools_reused: bool | None = None
            miss_reasons: list[str] = []
            if previous is None:
                miss_reasons.append("first_observed_call")
            else:
                system_head_reused = str(previous["system_head_hash"] or "") == system_head_hash
                tools_reused = str(previous["tools_hash"] or "") == tools_hash
                if not system_head_reused:
                    miss_reasons.append("system_head_changed")
                if not tools_reused:
                    miss_reasons.append("tools_changed")
                if not miss_reasons:
                    miss_reasons.append("prefix_stable")
            if not bool(payload.get("cache_eligible")):
                miss_reasons = ["cache_not_eligible"]

            await db.execute(
                """
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
                """,
                (
                    str(payload.get("request_id") or ""),
                    provider,
                    model,
                    request_kind,
                    session_id,
                    payload.get("turn_id"),
                    payload.get("agent_id"),
                    str(payload.get("cache_strategy") or "none"),
                    1 if payload.get("cache_eligible") else 0,
                    system_head_hash,
                    int(payload.get("system_head_chars") or 0),
                    str(payload.get("turn_context_hash") or ""),
                    int(payload.get("turn_context_chars") or 0),
                    tools_hash,
                    int(payload.get("tool_count") or 0),
                    json.dumps(list(payload.get("tool_names") or []), ensure_ascii=False),
                    self._bool_to_nullable_int(system_head_reused),
                    self._bool_to_nullable_int(tools_reused),
                    json.dumps(miss_reasons, ensure_ascii=False),
                    1 if payload.get("cache_fields_seen") else 0,
                    int(payload.get("cache_read_tokens") or 0),
                    int(payload.get("cache_write_tokens") or 0),
                    int(payload.get("cache_write_1h_tokens") or 0),
                    created_at,
                ),
            )
            await db.commit()

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
                """,
                (cutoff,),
            )

            # Costs are summed per native currency so a mixed USD+CNY window is
            # not collapsed into one meaningless number. Rows with no pricing
            # data (cost_currency IS NULL) are excluded.
            cost_by_currency_cursor = await db.execute(
                """
                SELECT cost_currency AS currency, COALESCE(SUM(cost_usd), 0) AS amount
                FROM llm_usage
                WHERE created_at >= ? AND cost_currency IS NOT NULL
                GROUP BY cost_currency
                ORDER BY amount DESC
                """,
                (cutoff,),
            )
            cost_by_currency_rows = await cost_by_currency_cursor.fetchall()
            cost_by_currency = [
                {"currency": str(row["currency"]), "amount": round(float(row["amount"] or 0), 4)}
                for row in cost_by_currency_rows
            ]

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
                "cache_read_tokens": int(totals["cache_read_tokens"] or 0),
                "cache_write_tokens": int(totals["cache_write_tokens"] or 0),
                "cache_write_1h_tokens": int(totals["cache_write_1h_tokens"] or 0),
                "cache_hit_rate": round(float(totals["cache_hit_rate"] or 0), 2),
                "avg_latency_ms": round(float(totals["avg_latency_ms"] or 0), 2),
                "avg_ttft_ms": round(float(totals["avg_ttft_ms"] or 0), 2) if float(totals["avg_ttft_ms"] or 0) > 0 else None,
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
