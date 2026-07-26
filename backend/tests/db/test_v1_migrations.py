"""Release migration-chain tests."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from types import ModuleType

from alembic import command
import pytest

from magi.db.runner import MIGRATION_TARGETS, _build_config, run_upgrade_head
from magi.utils.runtime import RuntimePaths

EXPECTED_TABLES: dict[str, set[str]] = {
    "chat": {
        "chat_sessions",
        "chat_message_asset_refs",
        "chat_run_consumed_events",
        "chat_user_turn_delivery",
    },
    "l1": {"fact_events", "l1_event_payload", "l1_session_sequences", "l1_source_facets"},
    "memory_shared": {
        "knowledge_graph",
        "knowledge_graph_versions",
        "manual_entries",
        "memory_corrections",
        "memory_correction_rules",
        "memory_relationship_conflict_effects",
        "memory_context_catalog",
        "memory_context_aliases",
        "memory_context_bindings",
        "memory_subject_revisions",
        "entity_name_evidence",
        "experiences",
        "experience_seeds",
        "user_portrait_projection",
    },
    "runtime_trace": {"trace_turns", "runtime_notifications", "user_notifications"},
    "llm_usage": {"llm_usage", "llm_usage_rollups", "llm_cache_observations"},
    "persona_registry": {"personas", "persona_active"},
    "behavior_evolution": {"task_interactions", "behavior_profiles"},
    "emotional": {"emotional_state", "emotional_events"},
    "growth_memory": {"milestones", "relationships", "personality_evolution"},
    "scheduler": {"schedules", "schedule_executions", "sensor_sync_jobs"},
    "sensor_state": {"sensor_cursors", "sensor_fingerprints", "sensor_stats"},
    "background_tasks": {
        "background_tasks",
        "background_task_events",
        "background_task_completion_intents",
    },
    "message_queue": {
        "runtime_commands",
        "runtime_command_rollups",
        "runtime_user_message_idempotency",
        "runtime_user_message_scope_blocks",
    },
    "permission_rules": {"permission_rules"},
    "channels": {"channel_session_mappings", "delivery_receipts", "outreach_outbox"},
    "identity": {"user_identity_bindings"},
    "batch": {"batch_job", "batch_item"},
}


def _revision_files(target_name: str) -> list[Path]:
    versions_dir = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "magi"
        / "db"
        / "migrations"
        / target_name
        / "versions"
    )
    return sorted(path for path in versions_dir.glob("*.py") if path.name != "__init__.py")


def _load_revision(path: Path, target_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"migration_{target_name}_{path.stem}",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _latest_revision(target_name: str) -> str:
    modules = [_load_revision(path, target_name) for path in _revision_files(target_name)]
    by_revision = {module.revision: module for module in modules}
    assert len(by_revision) == len(modules)
    assert "v1" in by_revision
    assert by_revision["v1"].down_revision is None

    children: dict[str, list[str]] = {revision: [] for revision in by_revision}
    for revision, module in by_revision.items():
        if revision == "v1":
            continue
        assert isinstance(module.down_revision, str)
        assert module.down_revision in by_revision
        children[module.down_revision].append(revision)

    assert all(len(next_revisions) <= 1 for next_revisions in children.values())
    heads = [revision for revision, next_revisions in children.items() if not next_revisions]
    assert len(heads) == 1

    visited = {"v1"}
    current = "v1"
    while children[current]:
        current = children[current][0]
        assert current not in visited
        visited.add(current)
    assert visited == set(by_revision)
    return heads[0]


def test_each_target_has_linear_migration_chain_starting_at_v1() -> None:
    for target in MIGRATION_TARGETS:
        files = _revision_files(target.name)

        assert files
        assert _latest_revision(target.name)


def test_migrations_build_runtime_schema_from_empty_directory(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)

    run_upgrade_head(runtime_paths)

    for target in MIGRATION_TARGETS:
        db_path = target.db_path(runtime_paths)
        assert db_path.exists(), f"{target.name} db was not created"

        with sqlite3.connect(db_path) as conn:
            tables = _table_names(conn)
            assert EXPECTED_TABLES[target.name] <= tables
            assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
                _latest_revision(target.name),
            )

    memory_db_path = next(t for t in MIGRATION_TARGETS if t.name == "memory_shared").db_path(
        runtime_paths
    )
    with sqlite3.connect(memory_db_path) as conn:
        assert "privacy_scope" not in _columns(conn, "knowledge_graph")
        assert {
            "l0_execution_runs",
            "l0_execution_pending_turns",
            "l0_execution_results",
        }.isdisjoint(_table_names(conn))
        assert "evidence_class" in _columns(conn, "knowledge_graph")
        assert "user_cover_asset_ref" in _columns(conn, "experiences")
        index_sql = conn.execute("""
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'idx_tom_assertions_active_unique'
            """).fetchone()[0]
        assert "shadow" in index_sql
        assert "slot_key" in index_sql
        assert "scope_key" in index_sql

    persona_db_path = next(
        target for target in MIGRATION_TARGETS if target.name == "persona_registry"
    ).db_path(runtime_paths)
    with sqlite3.connect(persona_db_path) as conn:
        builtin_seed_index = conn.execute("""
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'uq_personas_active_builtin_seed'
            """).fetchone()
        assert builtin_seed_index is not None
        assert "WHERE is_builtin = 1" in builtin_seed_index[0]
        assert "deleted_at IS NULL" in builtin_seed_index[0]

    message_queue_db_path = next(
        target for target in MIGRATION_TARGETS if target.name == "message_queue"
    ).db_path(runtime_paths)
    with sqlite3.connect(message_queue_db_path) as conn:
        assert "runtime_user_message_clear_state" in _table_names(conn)
        assert "user_message_generation" in _columns(conn, "runtime_commands")
        assert "runtime_user_message_idempotency" in _table_names(conn)
        assert "runtime_user_message_scope_blocks" in _table_names(conn)
        assert "delivery_status" in _columns(
            conn,
            "runtime_user_message_idempotency",
        )

    chat_db_path = next(
        target for target in MIGRATION_TARGETS if target.name == "chat"
    ).db_path(runtime_paths)
    with sqlite3.connect(chat_db_path) as conn:
        delivery_columns = _columns(conn, "chat_user_turn_delivery")
        assert {
            "delivery_attempt_no",
            "delivery_state",
            "current_command_id",
            "runtime_envelope_json",
        } <= delivery_columns
        assert "runtime_enqueued" not in delivery_columns


def test_chat_delivery_state_upgrades_from_pre_delta_v1(tmp_path: Path) -> None:
    target = next(item for item in MIGRATION_TARGETS if item.name == "chat")
    db_path = tmp_path / "chat-v1.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v1")

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE chat_user_turn_delivery")
        conn.execute("""
            CREATE TABLE chat_user_turn_delivery (
                turn_id TEXT PRIMARY KEY,
                projection_completed INTEGER NOT NULL DEFAULT 0,
                runtime_enqueued INTEGER NOT NULL DEFAULT 0,
                runtime_envelope_json TEXT NOT NULL DEFAULT '{}',
                request_fingerprint TEXT NOT NULL DEFAULT '',
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            )
            """)
        conn.execute("""
            INSERT INTO chat_turns (
                turn_id, session_id, user_id, status, response_mode,
                ux_plan_json, created_at_ms, updated_at_ms, run_revision
            ) VALUES ('turn-1', 'session-1', 'user-1', 'queued', 'direct', '{}', 1, 1, 0)
            """)
        conn.execute("""
            INSERT INTO chat_messages (
                message_id, session_id, turn_id, user_id, role, message_kind,
                payload_json, is_final, is_visible, created_at_ms, sequence_no
            ) VALUES (
                'message-1', 'session-1', 'turn-1', 'user-1', 'user',
                'user_text', '{}', 1, 1, 1, 1
            )
            """)
        conn.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("""
            SELECT projection_completed, delivery_attempt_no,
                   delivery_state, current_command_id
            FROM chat_user_turn_delivery
            WHERE turn_id = 'turn-1'
            """).fetchone() == (1, 0, "terminal", None)


@pytest.mark.asyncio
async def test_user_message_tombstone_upgrades_legacy_duplicate_correlations(
    tmp_path: Path,
) -> None:
    from magi.events.contracts import RuntimeCommandType
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    target = next(item for item in MIGRATION_TARGETS if item.name == "message_queue")
    db_path = tmp_path / "message-queue-v2.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v2")

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE runtime_user_message_idempotency")
        conn.execute("""
            INSERT INTO runtime_commands (
                command_type, payload_json, correlation_id, status,
                user_message_generation, created_at, updated_at
            ) VALUES ('user_message', '{"value": 1}', 'user_message:message-1',
                      'pending', 0, 1, 1)
            """)
        conn.execute("""
            INSERT INTO runtime_commands (
                command_type, payload_json, correlation_id, status,
                user_message_generation, created_at, updated_at
            ) VALUES ('user_message', '{"value": 2}', 'user_message:message-1',
                      'pending', 0, 2, 2)
            """)
        conn.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as conn:
        first_command_id = conn.execute("""
            SELECT command_id
            FROM runtime_commands
            WHERE correlation_id = 'user_message:message-1'
            ORDER BY command_id ASC
            LIMIT 1
            """).fetchone()[0]
        tombstone = conn.execute("""
            SELECT current_command_id, current_attempt_no, payload_fingerprint
            FROM runtime_user_message_idempotency
            WHERE correlation_id = 'user_message:message-1'
            """).fetchone()
        assert tombstone is not None
        assert tombstone[0] == first_command_id
        assert tombstone[1] == 0
        assert len(tombstone[2]) == 64
        assert conn.execute("""
            SELECT COUNT(*)
            FROM runtime_commands
            WHERE correlation_id = 'user_message:message-1'
              AND status IN ('pending', 'claimed')
            """).fetchone() == (1,)

    queue = SQLiteRuntimeCommandQueue(db_path=str(db_path))
    await queue.start()
    try:
        claimed = await queue.claim_next(
            consumer_name="migration-test",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert claimed is not None
        assert claimed.command_id == first_command_id
        await queue.ack(claimed.command_id)
        assert (
            await queue.claim_next(
                consumer_name="migration-test",
                command_types=(RuntimeCommandType.USER_MESSAGE,),
            )
            is None
        )
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_user_message_tombstone_drops_pending_duplicate_after_completion(
    tmp_path: Path,
) -> None:
    from magi.events.contracts import RuntimeCommandType
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    target = next(item for item in MIGRATION_TARGETS if item.name == "message_queue")
    db_path = tmp_path / "message-queue-completed-v2.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v2")

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE runtime_user_message_idempotency")
        completed_id = conn.execute("""
            INSERT INTO runtime_commands (
                command_type, payload_json, correlation_id, status,
                user_message_generation, created_at, updated_at
            ) VALUES ('user_message', '{"value": 1}', 'user_message:message-1',
                      'completed', 0, 1, 1)
            """).lastrowid
        conn.execute("""
            INSERT INTO runtime_commands (
                command_type, payload_json, correlation_id, status,
                user_message_generation, created_at, updated_at
            ) VALUES ('user_message', '{"value": 1}', 'user_message:message-1',
                      'pending', 0, 2, 2)
            """)
        conn.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("""
            SELECT current_command_id
            FROM runtime_user_message_idempotency
            WHERE correlation_id = 'user_message:message-1'
            """).fetchone() == (completed_id,)
        assert conn.execute("""
            SELECT COUNT(*)
            FROM runtime_commands
            WHERE correlation_id = 'user_message:message-1'
              AND status IN ('pending', 'claimed')
            """).fetchone() == (0,)

    queue = SQLiteRuntimeCommandQueue(db_path=str(db_path))
    await queue.start()
    try:
        assert (
            await queue.claim_next(
                consumer_name="migration-test",
                command_types=(RuntimeCommandType.USER_MESSAGE,),
            )
            is None
        )
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_failed_legacy_user_message_can_retry_after_upgrade_and_gc(
    tmp_path: Path,
) -> None:
    import json

    from magi.events.contracts import RuntimeCommandType, UserMessageCommand
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue

    target = next(item for item in MIGRATION_TARGETS if item.name == "message_queue")
    db_path = tmp_path / "message-queue-failed-v2.db"
    config = _build_config(target, db_path)
    command.upgrade(config, "v2")
    original = UserMessageCommand(
        source="api",
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        message="retry after failed GC",
        correlation_id="user_message:message-1",
        created_at=1710000000.0,
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE runtime_user_message_idempotency")
        failed_id = conn.execute(
            """
            INSERT INTO runtime_commands (
                command_type, payload_json, correlation_id, status,
                user_message_generation, created_at, updated_at
            ) VALUES (?, ?, ?, 'failed', 0, ?, ?)
            """,
            (
                RuntimeCommandType.USER_MESSAGE.value,
                json.dumps(original.to_payload(), ensure_ascii=False),
                original.correlation_id,
                original.created_at,
                original.created_at,
            ),
        ).lastrowid
        conn.commit()

    command.upgrade(config, "head")
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute(
                """
            SELECT current_attempt_no, current_command_id, delivery_status
            FROM runtime_user_message_idempotency
            WHERE correlation_id = ?
            """,
                (original.correlation_id,),
            ).fetchone()
            == (0, failed_id, "failed")
        )
        conn.execute(
            "DELETE FROM runtime_commands WHERE command_id = ?",
            (failed_id,),
        )
        conn.commit()

    queue = SQLiteRuntimeCommandQueue(db_path=str(db_path))
    await queue.start()
    try:
        same_attempt = await queue.schedule_user_message(original)
        assert same_attempt.command_id == failed_id
        assert (await queue.get_stats())["pending_count"] == 0
        retried_id = await queue.enqueue_user_message(
            UserMessageCommand(
                source=original.source,
                user_id=original.user_id,
                session_id=original.session_id,
                turn_id=original.turn_id,
                message=original.message,
                correlation_id=original.correlation_id,
                created_at=original.created_at,
                delivery_attempt_no=1,
            )
        )
        assert retried_id != failed_id
        with sqlite3.connect(db_path) as conn:
            assert (
                conn.execute(
                    """
                SELECT current_attempt_no, current_command_id, delivery_status
                FROM runtime_user_message_idempotency
                WHERE correlation_id = ?
                """,
                    (original.correlation_id,),
                ).fetchone()
                == (1, retried_id, "open")
            )
        claimed = await queue.claim_next(
            consumer_name="migration-test",
            command_types=(RuntimeCommandType.USER_MESSAGE,),
        )
        assert claimed is not None
        assert claimed.command_id == retried_id
    finally:
        await queue.stop()
