from __future__ import annotations

from importlib import import_module
from pathlib import Path

import aiosqlite
import pytest
from alembic import command

from magi.config.models import LifecycleSettings
from magi.core.runtime_operational_gc import RuntimeOperationalGC
from magi.core.sqlite import sqlite_connection_async
from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.llm.usage_store import LLMUsageStore


message_queue_initial = import_module("magi.db.migrations.message_queue.versions.v1_initial")
runtime_trace_initial = import_module("magi.db.migrations.runtime_trace.versions.v1_initial")
runtime_trace_journal = import_module(
	"magi.db.migrations.runtime_trace.versions.v2_agent_run_journal"
)
runtime_trace_plans = import_module("magi.db.migrations.runtime_trace.versions.v3_run_plans")
scheduler_initial = import_module("magi.db.migrations.scheduler.versions.v1_initial")
source_state_initial = import_module("magi.db.migrations.source_state.versions.v1_initial")


def _gc(base_dir: Path, *, now: float = 2_000_000.0, lifecycle: LifecycleSettings | None = None) -> RuntimeOperationalGC:
	from magi.utils.runtime import RuntimePaths
	runtime_paths = RuntimePaths(base_dir=base_dir)

	return RuntimeOperationalGC(
		lifecycle=lifecycle or LifecycleSettings(),
		llm_usage_store=LLMUsageStore(runtime_paths.llm_usage_db_path),
		runtime_paths=runtime_paths,
		now=lambda: now,
	)


async def _count_rows(db_path: Path, table_name: str, where: str = "1=1") -> int:
	async with sqlite_connection_async(db_path) as db:
		cursor = await db.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {where}")
		row = await cursor.fetchone()
	return int(row[0] or 0)


def _install_llm_usage_schema(db_path: Path) -> None:
	target = next(t for t in MIGRATION_TARGETS if t.name == "llm_usage")
	command.upgrade(_build_config(target, db_path), "head")


@pytest.mark.asyncio
async def test_runtime_trace_gc_deletes_expired_trace_and_terminal_events(tmp_path: Path) -> None:
	gc = _gc(tmp_path)
	db_path = gc.runtime_paths.runtime_trace_db_path
	old_ms = int((2_000_000.0 - (8 * 86400)) * 1000)
	recent_ms = int((2_000_000.0 - 60) * 1000)

	async with sqlite_connection_async(db_path) as db:
		await db.executescript(runtime_trace_initial.SCHEMA_SQL)
		await db.executescript(runtime_trace_journal.SCHEMA_SQL)
		await db.executescript(runtime_trace_plans.SCHEMA_SQL)
		await db.executemany(
			"""
			INSERT INTO agent_run_manifests (
				run_id, turn_id, session_id, user_id, manifest_json,
				created_at_ms, updated_at_ms
			) VALUES (?, ?, 's1', 'u1', '{}', ?, ?)
			""",
			(
				("run-old", "turn-old", old_ms, old_ms),
				("run-new", "turn-new", recent_ms, recent_ms),
			),
		)
		await db.executemany(
			"""
			INSERT INTO agent_run_events (
				event_id, run_id, sequence, turn_id, session_id, user_id,
				event_type, payload_json, created_at_ms
			) VALUES (?, ?, 1, ?, 's1', 'u1', 'run_completed', '{}', ?)
			""",
			(
				("event-old", "run-old", "turn-old", old_ms),
				("event-new", "run-new", "turn-new", recent_ms),
			),
		)
		await db.executemany(
			"""
			INSERT INTO run_plans (
				plan_id, run_id, session_id, version, required, status,
				plan_json, created_at_ms, updated_at_ms
			) VALUES (?, ?, 's1', 1, 1, 'active', '{}', ?, ?)
			""",
			(
				("plan-old", "run-old", old_ms, old_ms),
				("plan-new", "run-new", recent_ms, recent_ms),
			),
		)
		await db.executemany(
			"""
			INSERT INTO trace_turns (
				trace_id, turn_id, session_id, user_id, status, mode, started_at_ms,
				created_at_ms, updated_at_ms
			) VALUES (?, ?, 's1', 'u1', 'completed', 'chat', ?, ?, ?)
			""",
			(
				("trace-old", "turn-old", old_ms, old_ms, old_ms),
				("trace-new", "turn-new", recent_ms, recent_ms, recent_ms),
			),
		)
		await db.executemany(
			"""
			INSERT INTO trace_spans (
				span_id, trace_id, turn_id, node_type, name, status,
				started_at_ms, created_at_ms, updated_at_ms
			) VALUES (?, ?, ?, 'llm', 'model', 'completed', ?, ?, ?)
			""",
			(
				("span-old", "trace-old", "turn-old", old_ms, old_ms, old_ms),
				("span-new", "trace-new", "turn-new", recent_ms, recent_ms, recent_ms),
			),
		)
		await db.executemany(
			"""
			INSERT INTO runtime_notifications (
				channel, user_id, session_id, payload_json, created_at_ms
			) VALUES ('ui', 'u1', 's1', '{}', ?)
			""",
			((old_ms,), (recent_ms,)),
		)
		await db.executemany(
			"""
			INSERT INTO plugin_ingress_events (
				source_kind, producer, plugin_target, event_type, occurred_at_ms,
				payload_json, status, processed_at_ms, created_at_ms
			) VALUES ('source', 'p', 'calendar', 'event', ?, '{}', ?, ?, ?)
			""",
			(
				(old_ms, "completed", old_ms, old_ms),
				(old_ms, "pending", None, old_ms),
				(recent_ms, "failed", recent_ms, recent_ms),
			),
		)
		await db.commit()

	result = await gc.cleanup_runtime_trace()

	assert result["runtime_trace_trace_spans_deleted"] == 1
	assert result["runtime_trace_trace_turns_deleted"] == 1
	assert result["runtime_trace_run_plans_deleted"] == 1
	assert result["runtime_trace_agent_run_events_deleted"] == 1
	assert result["runtime_trace_agent_run_manifests_deleted"] == 1
	assert result["runtime_trace_notifications_deleted"] == 1
	assert result["runtime_trace_plugin_ingress_deleted"] == 1
	assert await _count_rows(db_path, "trace_turns") == 1
	assert await _count_rows(db_path, "trace_spans") == 1
	assert await _count_rows(db_path, "run_plans") == 1
	assert await _count_rows(db_path, "agent_run_events") == 1
	assert await _count_rows(db_path, "agent_run_manifests") == 1
	assert await _count_rows(db_path, "runtime_notifications") == 1
	assert await _count_rows(db_path, "plugin_ingress_events") == 2


@pytest.mark.asyncio
async def test_runtime_trace_gc_deletes_expired_user_notifications_but_keeps_unread(
	tmp_path: Path,
) -> None:
	gc = _gc(tmp_path)
	db_path = gc.runtime_paths.runtime_trace_db_path
	old_ms = int((2_000_000.0 - (31 * 86400)) * 1000)
	recent_ms = int((2_000_000.0 - 60) * 1000)

	async with sqlite_connection_async(db_path) as db:
		await db.executescript(runtime_trace_initial.SCHEMA_SQL)
		await db.executemany(
			"""
			INSERT INTO user_notifications (
				user_id, kind, dedupe_key, title, body, status, created_at_ms
			) VALUES ('default_user', 'suggestion', ?, 't', 'b', ?, ?)
			""",
			(
				("old-unread", "unread", old_ms),
				("old-read", "read", old_ms),
				("old-dismissed", "dismissed", old_ms),
				("recent-read", "read", recent_ms),
			),
		)
		await db.commit()

	result = await gc.cleanup_runtime_trace()

	# Only the two old, non-unread rows are deleted; old unread + recent survive.
	assert result["user_notifications_deleted"] == 2
	assert await _count_rows(db_path, "user_notifications") == 2
	assert await _count_rows(db_path, "user_notifications", "status = 'unread'") == 1
	assert await _count_rows(
		db_path, "user_notifications", "created_at_ms = " + str(recent_ms)
	) == 1


@pytest.mark.asyncio
async def test_llm_usage_gc_rolls_up_and_deletes_expired_raw_rows(tmp_path: Path) -> None:
	gc = _gc(tmp_path)
	db_path = gc.runtime_paths.llm_usage_db_path
	old_ts = 2_000_000.0 - (8 * 86400)
	recent_ts = 2_000_000.0 - 60

	_install_llm_usage_schema(db_path)
	async with sqlite_connection_async(db_path) as db:
		await db.executemany(
			"""
			INSERT INTO llm_usage (
				request_id, provider, model, request_kind, prompt_tokens,
				completion_tokens, total_tokens, usage_available, latency_ms,
				ttft_ms, cache_read_tokens, cache_write_tokens,
				cache_write_1h_tokens, cost_usd, success, created_at
			) VALUES (?, 'openai', 'gpt-test', 'chat', ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 1, ?)
			""",
			(
				("old-1", 10, 20, 30, 100, 40, 7, 3, 1, 0.01, old_ts),
				("old-2", 5, 10, 15, 80, 30, 4, 2, 0, 0.02, old_ts + 10),
				("new-1", 1, 2, 3, 20, 10, 1, 1, 0, 0.001, recent_ts),
			),
		)
		await db.commit()

	result = await gc.cleanup_llm_usage()

	assert result["llm_usage_rows_rolled_up"] == 2
	assert result["llm_usage_raw_deleted"] == 2
	assert await _count_rows(db_path, "llm_usage") == 1
	async with sqlite_connection_async(db_path) as db:
		db.row_factory = aiosqlite.Row
		cursor = await db.execute(
			"SELECT calls, total_tokens, cache_read_tokens, cache_write_tokens, "
			"cache_write_1h_tokens, cost_usd FROM llm_usage_rollups"
		)
		row = await cursor.fetchone()
	assert row is not None
	assert int(row["calls"]) == 2
	assert int(row["total_tokens"]) == 45
	assert int(row["cache_read_tokens"]) == 11
	assert int(row["cache_write_tokens"]) == 5
	assert int(row["cache_write_1h_tokens"]) == 1
	assert float(row["cost_usd"]) == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_llm_usage_gc_prunes_cache_observations_by_retention_and_max_rows(tmp_path: Path) -> None:
	lifecycle = LifecycleSettings(
		llm_usage={
			"cache_observability": {
				"enabled": True,
				"retention_days": 30,
				"max_rows": 2,
			}
		}
	)
	gc = _gc(tmp_path, lifecycle=lifecycle)
	db_path = gc.runtime_paths.llm_usage_db_path
	old_ts = 2_000_000.0 - (31 * 86400)
	recent_a = 2_000_000.0 - 300
	recent_b = 2_000_000.0 - 200
	recent_c = 2_000_000.0 - 100

	_install_llm_usage_schema(db_path)
	async with sqlite_connection_async(db_path) as db:
		await db.executemany(
			"""
			INSERT INTO llm_cache_observations (
				request_id, provider, model, request_kind, session_id,
				cache_strategy, cache_eligible, system_head_hash, tools_hash,
				created_at
			) VALUES (?, 'openai', 'gpt-test', 'chat', 's1',
				'prompt_cache_key', 1, 'head', ?, ?)
			""",
			(
				("old", "tools-old", old_ts),
				("recent-a", "tools-a", recent_a),
				("recent-b", "tools-b", recent_b),
				("recent-c", "tools-c", recent_c),
			),
		)
		await db.commit()

	result = await gc.cleanup_llm_usage()

	assert result["llm_cache_observations_deleted"] == 1
	assert result["llm_cache_observations_trimmed"] == 1
	assert await _count_rows(db_path, "llm_cache_observations") == 2
	async with sqlite_connection_async(db_path) as db:
		cursor = await db.execute(
			"SELECT request_id FROM llm_cache_observations ORDER BY created_at ASC"
		)
		rows = await cursor.fetchall()
	assert [row[0] for row in rows] == ["recent-b", "recent-c"]


@pytest.mark.asyncio
async def test_message_queue_gc_rolls_up_completed_and_preserves_active_rows(tmp_path: Path) -> None:
	gc = _gc(tmp_path)
	db_path = gc.runtime_paths.message_queue_db_path
	old_completed = 2_000_000.0 - (26 * 3600)
	old_failed = 2_000_000.0 - (8 * 86400)
	active_old = 2_000_000.0 - (30 * 86400)
	recent = 2_000_000.0 - 60

	async with sqlite_connection_async(db_path) as db:
		await db.executescript(message_queue_initial.SCHEMA_SQL)
		await db.executemany(
			"""
			INSERT INTO runtime_commands (
				command_type, payload_json, correlation_id, status, retry_count,
				created_at, updated_at
			) VALUES (?, '{}', ?, ?, ?, ?, ?)
			""",
			(
				("user_message", "c1", "completed", 2, old_completed, old_completed),
				("user_message", "c2", "completed", 0, recent, recent),
				("source_sync", "c3", "failed", 1, old_failed, old_failed),
				("source_sync", "c4", "pending", 0, active_old, active_old),
			),
		)
		await db.commit()

	result = await gc.cleanup_message_queue()

	assert result["message_queue_completed_rolled_up"] == 1
	assert result["message_queue_completed_deleted"] == 1
	assert result["message_queue_failed_deleted"] == 1
	assert await _count_rows(db_path, "runtime_commands") == 2
	assert await _count_rows(db_path, "runtime_commands", "status = 'pending'") == 1
	async with sqlite_connection_async(db_path) as db:
		db.row_factory = aiosqlite.Row
		cursor = await db.execute("SELECT commands, retries FROM runtime_command_rollups")
		row = await cursor.fetchone()
	assert row is not None
	assert int(row["commands"]) == 1
	assert int(row["retries"]) == 2


@pytest.mark.asyncio
async def test_scheduler_and_source_state_gc_remove_only_expired_history(tmp_path: Path) -> None:
	lifecycle = LifecycleSettings(source_state={"fingerprints_keep_latest": 3})
	gc = _gc(tmp_path, lifecycle=lifecycle)
	scheduler_db_path = gc.runtime_paths.scheduler_db_path
	source_db_path = gc.runtime_paths.source_state_db_path
	old_success = 2_000_000.0 - (31 * 86400)
	old_failed = 2_000_000.0 - (61 * 86400)
	recent = 2_000_000.0 - 60

	async with sqlite_connection_async(scheduler_db_path) as db:
		await db.executescript(scheduler_initial.SCHEMA_SQL)
		await db.executemany(
			"""
			INSERT INTO schedule_executions (
				execution_id, schedule_id, target_type, target_key, status,
				started_at, finished_at, created_at
			) VALUES (?, 'sched', 'source', 'calendar', ?, ?, ?, ?)
			""",
			(
				("exec-success-old", "success", old_success, old_success, old_success),
				("exec-failed-old", "failed", old_failed, old_failed, old_failed),
				("exec-running-old", "running", old_failed, None, old_failed),
				("exec-success-new", "success", recent, recent, recent),
			),
		)
		await db.executemany(
			"""
			INSERT INTO source_sync_jobs (
				job_id, schedule_id, execution_id, target_type, target_key,
				plugin_id, source_type, status, payload_json, created_at,
				started_at, finished_at
			) VALUES (?, 'sched', ?, 'source', 'calendar', 'calendar', 'calendar', ?, '{}', ?, ?, ?)
			""",
			(
				("job-success-old", "exec-success-old", "success", old_success, old_success, old_success),
				("job-failed-old", "exec-failed-old", "failed", old_failed, old_failed, old_failed),
				("job-queued-old", "exec-running-old", "queued", old_failed, None, None),
			),
		)
		await db.commit()

	async with sqlite_connection_async(source_db_path) as db:
		await db.executescript(source_state_initial.SCHEMA_SQL)
		await db.executemany(
			"""
			INSERT INTO source_fingerprints (source_id, fingerprint, created_at)
			VALUES ('calendar', ?, ?)
			""",
			tuple((f"fingerprint-{index}", float(index)) for index in range(5)),
		)
		await db.commit()

	scheduler_result = await gc.cleanup_scheduler()
	source_result = await gc.cleanup_source_state()

	assert scheduler_result["scheduler_success_executions_deleted"] == 1
	assert scheduler_result["scheduler_failed_executions_deleted"] == 1
	assert scheduler_result["scheduler_success_source_jobs_deleted"] == 1
	assert scheduler_result["scheduler_failed_source_jobs_deleted"] == 1
	assert source_result["source_state_fingerprints_deleted"] == 2
	assert await _count_rows(scheduler_db_path, "schedule_executions") == 2
	assert await _count_rows(scheduler_db_path, "source_sync_jobs") == 1
	assert await _count_rows(source_db_path, "source_fingerprints") == 3
