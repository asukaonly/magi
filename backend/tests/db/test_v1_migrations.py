"""Release baseline migration tests."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from types import ModuleType

from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
from magi.utils.runtime import RuntimePaths


EXPECTED_TABLES: dict[str, set[str]] = {
    "chat": {"chat_sessions", "chat_run_consumed_events"},
    "l1": {"fact_events", "l1_event_payload", "l1_session_sequences", "l1_source_facets"},
    "memory_shared": {
        "knowledge_graph",
        "manual_entries",
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
    "background_tasks": {"background_tasks", "background_task_events"},
    "message_queue": {"runtime_commands", "runtime_command_rollups"},
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
    return sorted(
        path
        for path in versions_dir.glob("*.py")
        if path.name != "__init__.py"
    )


def _load_revision(path: Path, target_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"migration_{target_name}_v1", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row[0] for row in rows}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_each_target_has_one_v1_initial_revision() -> None:
    for target in MIGRATION_TARGETS:
        files = _revision_files(target.name)

        assert [file.name for file in files] == ["v1_initial.py"]
        module = _load_revision(files[0], target.name)
        assert module.revision == "v1"
        assert module.down_revision is None


def test_v1_migrations_build_runtime_schema_from_empty_directory(tmp_path: Path) -> None:
    runtime_paths = RuntimePaths(base_dir=tmp_path)

    run_upgrade_head(runtime_paths)

    for target in MIGRATION_TARGETS:
        db_path = target.db_path(runtime_paths)
        assert db_path.exists(), f"{target.name} db was not created"

        with sqlite3.connect(db_path) as conn:
            tables = _table_names(conn)
            assert EXPECTED_TABLES[target.name] <= tables
            assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("v1",)

    memory_db_path = next(t for t in MIGRATION_TARGETS if t.name == "memory_shared").db_path(runtime_paths)
    with sqlite3.connect(memory_db_path) as conn:
        assert "privacy_scope" not in _columns(conn, "knowledge_graph")
        assert "trigger_json" in _columns(conn, "l0_execution_runs")
        assert "evidence_class" in _columns(conn, "knowledge_graph")
        assert "user_cover_asset_ref" in _columns(conn, "experiences")
        index_sql = conn.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'idx_tom_assertions_active_unique'
            """
        ).fetchone()[0]
        assert "shadow" in index_sql
