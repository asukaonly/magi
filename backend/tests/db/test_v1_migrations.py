"""Release migration-chain tests."""

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
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
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

    persona_db_path = next(
        target for target in MIGRATION_TARGETS if target.name == "persona_registry"
    ).db_path(runtime_paths)
    with sqlite3.connect(persona_db_path) as conn:
        builtin_seed_index = conn.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'uq_personas_active_builtin_seed'
            """
        ).fetchone()
        assert builtin_seed_index is not None
        assert "WHERE is_builtin = 1" in builtin_seed_index[0]
        assert "deleted_at IS NULL" in builtin_seed_index[0]
