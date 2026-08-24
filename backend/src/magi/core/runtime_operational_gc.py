"""Operational SQLite cleanup for runtime-only local stores."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import aiosqlite

from ..utils.runtime import RuntimePaths, get_runtime_paths
from .logger import get_logger
from .sqlite import sqlite_connection_async

logger = get_logger(__name__)


LLM_USAGE_ROLLUP_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS llm_usage_rollups (
    granularity TEXT NOT NULL,
    bucket_start TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    request_kind TEXT NOT NULL,
    success INTEGER NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    calls_with_usage INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_1h_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    latency_ms_total INTEGER NOT NULL DEFAULT 0,
    ttft_ms_total INTEGER NOT NULL DEFAULT 0,
    ttft_ms_count INTEGER NOT NULL DEFAULT 0,
    last_rolled_up_at REAL NOT NULL,
    PRIMARY KEY (granularity, bucket_start, provider, model, request_kind, success)
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_rollups_bucket
    ON llm_usage_rollups(granularity, bucket_start);
"""

RUNTIME_COMMAND_ROLLUP_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runtime_command_rollups (
    granularity TEXT NOT NULL,
    bucket_start TEXT NOT NULL,
    command_type TEXT NOT NULL,
    status TEXT NOT NULL,
    commands INTEGER NOT NULL DEFAULT 0,
    retries INTEGER NOT NULL DEFAULT 0,
    last_rolled_up_at REAL NOT NULL,
    PRIMARY KEY (granularity, bucket_start, command_type, status)
);
CREATE INDEX IF NOT EXISTS idx_runtime_command_rollups_bucket
    ON runtime_command_rollups(granularity, bucket_start);
"""


class RuntimeOperationalGC:
    """Run retention and rollup cleanup for operational runtime stores."""

    def __init__(
        self,
        *,
        lifecycle: Any,  # config.models.LifecycleSettings, injected by the
        # composition root (bootstrap/maintenance.py). Typed Any so this L1
        # core module does not import the higher config layer.
        llm_usage_store: Any,
        runtime_paths: RuntimePaths | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.lifecycle = lifecycle
        self._llm_usage_store = llm_usage_store
        self.runtime_paths = runtime_paths or get_runtime_paths()
        self._now = now or time.time

    async def run(self) -> dict[str, int]:
        """Run all operational cleanup groups and return affected-row counts."""

        results: dict[str, int] = {}
        for label, cleanup in (
            ("runtime_trace", self.cleanup_runtime_trace),
            ("llm_usage", self.cleanup_llm_usage),
            ("message_queue", self.cleanup_message_queue),
            ("scheduler", self.cleanup_scheduler),
            ("sensor_state", self.cleanup_sensor_state),
        ):
            try:
                results.update(await cleanup())
            except Exception as exc:
                logger.warning(
                    "runtime_operational_gc.%s_failed", label, error=str(exc), exc_info=True
                )
                results[f"runtime_gc_{label}_errors"] = 1
        return results

    async def cleanup_runtime_trace(self) -> dict[str, int]:
        """Delete expired trace, notification, and plugin ingress rows."""

        db_path = self.runtime_paths.runtime_trace_db_path
        if not db_path.exists():
            return {}

        settings = self.lifecycle.runtime_trace
        trace_cutoff_ms = self._cutoff_ms(settings.raw_retention_days)
        notifications_cutoff_ms = self._cutoff_ms(settings.notifications_retention_days)
        plugin_ingress_cutoff_ms = self._cutoff_ms(settings.plugin_ingress_retention_days)

        async with sqlite_connection_async(db_path, profile="mixed") as db:
            if not await self._table_exists(db, "trace_turns"):
                return {}

            counts: dict[str, int] = {}
            if await self._table_exists(db, "run_plans"):
                counts["runtime_trace_run_plans_deleted"] = await self._delete_rows(
                    db,
                    "DELETE FROM run_plans WHERE created_at_ms < ?",
                    (trace_cutoff_ms,),
                )
            if await self._table_exists(db, "agent_run_manifests"):
                if await self._table_exists(db, "agent_run_events"):
                    counts["runtime_trace_agent_run_events_deleted"] = await self._delete_rows(
                        db,
                        """
                        DELETE FROM agent_run_events
                        WHERE run_id IN (
                            SELECT run_id FROM agent_run_manifests WHERE created_at_ms < ?
                        )
                        """,
                        (trace_cutoff_ms,),
                    )
                counts["runtime_trace_agent_run_manifests_deleted"] = await self._delete_rows(
                    db,
                    "DELETE FROM agent_run_manifests WHERE created_at_ms < ?",
                    (trace_cutoff_ms,),
                )
            for table_name in (
                "trace_llm_calls",
                "trace_tools",
                "trace_spans",
            ):
                if await self._table_exists(db, table_name):
                    counts[f"runtime_trace_{table_name}_deleted"] = await self._delete_rows(
                        db,
                        f"""
                        DELETE FROM {table_name}
                        WHERE trace_id IN (
                            SELECT trace_id FROM trace_turns WHERE started_at_ms < ?
                        )
                        """,
                        (trace_cutoff_ms,),
                    )

            counts["runtime_trace_trace_turns_deleted"] = await self._delete_rows(
                db,
                "DELETE FROM trace_turns WHERE started_at_ms < ?",
                (trace_cutoff_ms,),
            )

            if await self._table_exists(db, "runtime_notifications"):
                counts["runtime_trace_notifications_deleted"] = await self._delete_rows(
                    db,
                    "DELETE FROM runtime_notifications WHERE created_at_ms < ?",
                    (notifications_cutoff_ms,),
                )

            un_cutoff_ms = self._cutoff_ms(settings.user_notifications_retention_days)
            if await self._table_exists(db, "user_notifications"):
                counts["user_notifications_deleted"] = await self._delete_rows(
                    db,
                    "DELETE FROM user_notifications WHERE status != 'unread' AND created_at_ms < ?",
                    (un_cutoff_ms,),
                )

            if await self._table_exists(db, "plugin_ingress_events"):
                counts["runtime_trace_plugin_ingress_deleted"] = await self._delete_rows(
                    db,
                    """
                    DELETE FROM plugin_ingress_events
                    WHERE status IN ('completed', 'failed')
                      AND COALESCE(processed_at_ms, created_at_ms) < ?
                    """,
                    (plugin_ingress_cutoff_ms,),
                )

            await db.commit()
        return counts

    async def cleanup_llm_usage(self) -> dict[str, int]:
        """Roll up and delete expired raw LLM usage rows."""

        async with self._llm_usage_store.user_content_operation():
            return await self._cleanup_llm_usage_unlocked()

    async def _cleanup_llm_usage_unlocked(self) -> dict[str, int]:
        """Run retention while the shared usage-content boundary is held."""

        db_path = self.runtime_paths.llm_usage_db_path
        if not db_path.exists():
            return {}

        settings = self.lifecycle.llm_usage
        cutoff = self._cutoff_seconds(settings.raw_retention_days)
        rollup_cutoff_bucket = self._bucket_start(
            self._cutoff_seconds(settings.rollup_retention_days),
            settings.rollup_granularity,
        )

        async with sqlite_connection_async(db_path, profile="mixed") as db:
            if not await self._table_exists(db, "llm_usage"):
                return {}
            await db.executescript(LLM_USAGE_ROLLUP_SCHEMA_SQL)

            rolled_up = await self._rollup_llm_usage(db, cutoff=cutoff)
            deleted = await self._delete_rows(
                db,
                "DELETE FROM llm_usage WHERE created_at < ?",
                (cutoff,),
            )
            cache_observations_deleted, cache_observations_trimmed = (
                await self._cleanup_llm_cache_observations(db, settings)
            )
            rollups_deleted = await self._cleanup_llm_usage_rollups(
                db,
                granularity=settings.rollup_granularity,
                cutoff_bucket=rollup_cutoff_bucket,
            )
            await db.commit()

        return {
            "llm_usage_rows_rolled_up": rolled_up,
            "llm_usage_raw_deleted": deleted,
            "llm_usage_rollups_deleted": rollups_deleted,
            "llm_cache_observations_deleted": cache_observations_deleted,
            "llm_cache_observations_trimmed": cache_observations_trimmed,
        }

    async def _cleanup_llm_cache_observations(
        self, db: aiosqlite.Connection, settings: Any
    ) -> tuple[int, int]:
        if not await self._table_exists(db, "llm_cache_observations"):
            return 0, 0
        cache_observability = getattr(settings, "cache_observability", None)
        if cache_observability is not None and not bool(
            getattr(cache_observability, "enabled", True)
        ):
            deleted = await self._delete_rows(
                db,
                "DELETE FROM llm_cache_observations",
                (),
            )
            return deleted, 0
        return await self._prune_llm_cache_observations(db, cache_observability)

    async def _prune_llm_cache_observations(
        self, db: aiosqlite.Connection, cache_observability: Any
    ) -> tuple[int, int]:
        retention_days = int(
            getattr(cache_observability, "retention_days", 30)
            if cache_observability is not None
            else 30
        )
        max_rows = int(
            getattr(cache_observability, "max_rows", 50_000)
            if cache_observability is not None
            else 50_000
        )
        observation_cutoff = self._cutoff_seconds(retention_days)
        deleted = await self._delete_rows(
            db,
            "DELETE FROM llm_cache_observations WHERE created_at < ?",
            (observation_cutoff,),
        )
        trimmed = await self._delete_rows(
            db,
            """
            DELETE FROM llm_cache_observations
            WHERE id IN (
                SELECT id
                FROM llm_cache_observations
                ORDER BY created_at DESC, id DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (max_rows,),
        )
        return deleted, trimmed

    async def _cleanup_llm_usage_rollups(
        self, db: aiosqlite.Connection, *, granularity: str, cutoff_bucket: str
    ) -> int:
        return await self._delete_rows(
            db,
            "DELETE FROM llm_usage_rollups WHERE granularity = ? AND bucket_start < ?",
            (granularity, cutoff_bucket),
        )

    async def cleanup_message_queue(self) -> dict[str, int]:
        """Roll up completed commands and delete terminal queue history."""

        db_path = self.runtime_paths.message_queue_db_path
        if not db_path.exists():
            return {}

        settings = self.lifecycle.message_queue
        completed_cutoff = self._now() - (settings.completed.raw_retention_hours * 3600)
        failed_cutoff = self._cutoff_seconds(settings.failed.raw_retention_days)
        rollup_cutoff_bucket = self._bucket_start(
            self._cutoff_seconds(settings.completed.rollup_retention_days),
            settings.completed.rollup_granularity,
        )

        async with sqlite_connection_async(db_path, profile="mixed") as db:
            if not await self._table_exists(db, "runtime_commands"):
                return {}
            await db.executescript(RUNTIME_COMMAND_ROLLUP_SCHEMA_SQL)

            rolled_up = await self._rollup_runtime_commands(db, cutoff=completed_cutoff)
            completed_deleted = await self._delete_rows(
                db,
                "DELETE FROM runtime_commands WHERE status = 'completed' AND updated_at < ?",
                (completed_cutoff,),
            )
            failed_deleted = await self._delete_rows(
                db,
                "DELETE FROM runtime_commands WHERE status = 'failed' AND updated_at < ?",
                (failed_cutoff,),
            )
            rollups_deleted = await self._delete_rows(
                db,
                "DELETE FROM runtime_command_rollups WHERE granularity = ? AND bucket_start < ?",
                (settings.completed.rollup_granularity, rollup_cutoff_bucket),
            )
            await db.commit()

        return {
            "message_queue_completed_rolled_up": rolled_up,
            "message_queue_completed_deleted": completed_deleted,
            "message_queue_failed_deleted": failed_deleted,
            "message_queue_rollups_deleted": rollups_deleted,
        }

    async def cleanup_scheduler(self) -> dict[str, int]:
        """Delete expired scheduler execution and sensor sync job history."""

        db_path = self.runtime_paths.scheduler_db_path
        if not db_path.exists():
            return {}

        settings = self.lifecycle.scheduler
        execution_success_cutoff = self._cutoff_seconds(settings.executions.success_retention_days)
        execution_failed_cutoff = self._cutoff_seconds(settings.executions.failed_retention_days)
        job_success_cutoff = self._cutoff_seconds(settings.sensor_sync_jobs.success_retention_days)
        job_failed_cutoff = self._cutoff_seconds(settings.sensor_sync_jobs.failed_retention_days)

        async with sqlite_connection_async(db_path, profile="mixed") as db:
            counts: dict[str, int] = {}
            if await self._table_exists(db, "schedule_executions"):
                counts["scheduler_success_executions_deleted"] = await self._delete_rows(
                    db,
                    """
                    DELETE FROM schedule_executions
                    WHERE status = 'success'
                      AND COALESCE(finished_at, started_at, created_at) < ?
                    """,
                    (execution_success_cutoff,),
                )
                counts["scheduler_failed_executions_deleted"] = await self._delete_rows(
                    db,
                    """
                    DELETE FROM schedule_executions
                    WHERE status = 'failed'
                      AND COALESCE(finished_at, started_at, created_at) < ?
                    """,
                    (execution_failed_cutoff,),
                )

            if await self._table_exists(db, "sensor_sync_jobs"):
                counts["scheduler_success_sensor_jobs_deleted"] = await self._delete_rows(
                    db,
                    """
                    DELETE FROM sensor_sync_jobs
                    WHERE status = 'success'
                      AND COALESCE(finished_at, started_at, created_at) < ?
                    """,
                    (job_success_cutoff,),
                )
                counts["scheduler_failed_sensor_jobs_deleted"] = await self._delete_rows(
                    db,
                    """
                    DELETE FROM sensor_sync_jobs
                    WHERE status = 'failed'
                      AND COALESCE(finished_at, started_at, created_at) < ?
                    """,
                    (job_failed_cutoff,),
                )

            await db.commit()
        return counts

    async def cleanup_sensor_state(self) -> dict[str, int]:
        """Prune old sensor fingerprints while retaining recent cursors and stats."""

        db_path = self.runtime_paths.sensor_state_db_path
        if not db_path.exists():
            return {}

        keep_latest = self.lifecycle.sensor_state.fingerprints_keep_latest
        async with sqlite_connection_async(db_path, profile="mixed") as db:
            if not await self._table_exists(db, "sensor_fingerprints"):
                return {}
            cursor = await db.execute("SELECT DISTINCT sensor_id FROM sensor_fingerprints")
            rows = await cursor.fetchall()
            deleted = 0
            for row in rows:
                sensor_id = str(row[0])
                deleted += await self._prune_sensor_fingerprints(
                    db, sensor_id, keep_latest=keep_latest
                )
            await db.commit()
        return {"sensor_state_fingerprints_deleted": deleted}

    async def _rollup_llm_usage(self, db: aiosqlite.Connection, *, cutoff: float) -> int:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM llm_usage WHERE created_at < ?",
            (cutoff,),
        )
        row = await cursor.fetchone()
        row_count = int(row[0] or 0) if row else 0
        if row_count <= 0:
            return 0

        granularity = self.lifecycle.llm_usage.rollup_granularity
        bucket_expression = self._sqlite_bucket_expression("created_at", granularity)
        await db.execute(
            f"""
            INSERT INTO llm_usage_rollups (
                granularity, bucket_start, provider, model, request_kind, success,
                calls, calls_with_usage, prompt_tokens, completion_tokens, total_tokens,
                cache_read_tokens, cache_write_tokens, cache_write_1h_tokens,
                cost_usd, latency_ms_total, ttft_ms_total, ttft_ms_count, last_rolled_up_at
            )
            SELECT
                ?,
                {bucket_expression},
                provider,
                model,
                request_kind,
                success,
                COUNT(*),
                COALESCE(SUM(CASE WHEN usage_available = 1 THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(prompt_tokens), 0),
                COALESCE(SUM(completion_tokens), 0),
                COALESCE(SUM(total_tokens), 0),
                COALESCE(SUM(cache_read_tokens), 0),
                COALESCE(SUM(cache_write_tokens), 0),
                COALESCE(SUM(cache_write_1h_tokens), 0),
                COALESCE(SUM(cost_usd), 0),
                COALESCE(SUM(latency_ms), 0),
                COALESCE(SUM(CASE WHEN ttft_ms > 0 THEN ttft_ms ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN ttft_ms > 0 THEN 1 ELSE 0 END), 0),
                ?
            FROM llm_usage
            WHERE created_at < ?
            GROUP BY {bucket_expression}, provider, model, request_kind, success
            ON CONFLICT(granularity, bucket_start, provider, model, request_kind, success)
            DO UPDATE SET
                calls = llm_usage_rollups.calls + excluded.calls,
                calls_with_usage = llm_usage_rollups.calls_with_usage + excluded.calls_with_usage,
                prompt_tokens = llm_usage_rollups.prompt_tokens + excluded.prompt_tokens,
                completion_tokens = llm_usage_rollups.completion_tokens + excluded.completion_tokens,
                total_tokens = llm_usage_rollups.total_tokens + excluded.total_tokens,
                cache_read_tokens = llm_usage_rollups.cache_read_tokens + excluded.cache_read_tokens,
                cache_write_tokens = llm_usage_rollups.cache_write_tokens + excluded.cache_write_tokens,
                cache_write_1h_tokens = llm_usage_rollups.cache_write_1h_tokens + excluded.cache_write_1h_tokens,
                cost_usd = llm_usage_rollups.cost_usd + excluded.cost_usd,
                latency_ms_total = llm_usage_rollups.latency_ms_total + excluded.latency_ms_total,
                ttft_ms_total = llm_usage_rollups.ttft_ms_total + excluded.ttft_ms_total,
                ttft_ms_count = llm_usage_rollups.ttft_ms_count + excluded.ttft_ms_count,
                last_rolled_up_at = excluded.last_rolled_up_at
            """,
            (granularity, self._now(), cutoff),
        )
        return row_count

    async def _rollup_runtime_commands(self, db: aiosqlite.Connection, *, cutoff: float) -> int:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM runtime_commands WHERE status = 'completed' AND updated_at < ?",
            (cutoff,),
        )
        row = await cursor.fetchone()
        row_count = int(row[0] or 0) if row else 0
        if row_count <= 0:
            return 0

        granularity = self.lifecycle.message_queue.completed.rollup_granularity
        bucket_expression = self._sqlite_bucket_expression("updated_at", granularity)
        await db.execute(
            f"""
            INSERT INTO runtime_command_rollups (
                granularity, bucket_start, command_type, status, commands, retries, last_rolled_up_at
            )
            SELECT
                ?,
                {bucket_expression},
                command_type,
                status,
                COUNT(*),
                COALESCE(SUM(retry_count), 0),
                ?
            FROM runtime_commands
            WHERE status = 'completed'
              AND updated_at < ?
            GROUP BY {bucket_expression}, command_type, status
            ON CONFLICT(granularity, bucket_start, command_type, status)
            DO UPDATE SET
                commands = runtime_command_rollups.commands + excluded.commands,
                retries = runtime_command_rollups.retries + excluded.retries,
                last_rolled_up_at = excluded.last_rolled_up_at
            """,
            (granularity, self._now(), cutoff),
        )
        return row_count

    async def _prune_sensor_fingerprints(
        self,
        db: aiosqlite.Connection,
        sensor_id: str,
        *,
        keep_latest: int,
    ) -> int:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM sensor_fingerprints WHERE sensor_id = ?",
            (sensor_id,),
        )
        row = await cursor.fetchone()
        total = int(row[0] or 0) if row else 0
        to_delete = max(0, total - int(keep_latest))
        if to_delete <= 0:
            return 0
        cursor = await db.execute(
            """
            DELETE FROM sensor_fingerprints
            WHERE rowid IN (
                SELECT rowid
                FROM sensor_fingerprints
                WHERE sensor_id = ?
                ORDER BY created_at ASC, fingerprint ASC
                LIMIT ?
            )
            """,
            (sensor_id, to_delete),
        )
        return int(cursor.rowcount or 0)

    def _cutoff_seconds(self, retention_days: int) -> float:
        return self._now() - (max(1, int(retention_days)) * 86400)

    def _cutoff_ms(self, retention_days: int) -> int:
        return int(self._cutoff_seconds(retention_days) * 1000)

    @staticmethod
    async def _table_exists(db: aiosqlite.Connection, table_name: str) -> bool:
        cursor = await db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
        return await cursor.fetchone() is not None

    @staticmethod
    async def _delete_rows(
        db: aiosqlite.Connection,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> int:
        cursor = await db.execute(sql, params)
        return int(cursor.rowcount or 0)

    @staticmethod
    def _sqlite_bucket_expression(column_name: str, granularity: str) -> str:
        if granularity == "hour":
            return f"strftime('%Y-%m-%dT%H:00:00', datetime({column_name}, 'unixepoch'))"
        return f"strftime('%Y-%m-%d', datetime({column_name}, 'unixepoch'))"

    @staticmethod
    def _bucket_start(timestamp: float, granularity: str) -> str:
        time_struct = time.gmtime(timestamp)
        if granularity == "hour":
            return time.strftime("%Y-%m-%dT%H:00:00", time_struct)
        return time.strftime("%Y-%m-%d", time_struct)
