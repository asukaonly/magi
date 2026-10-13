"""Retention cursor migrations and indexed keyset reads."""

import sqlite3

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.memory.l3.source_event_governance import active_summary_predicate
from magi.memory.portability.storage import clear_portability_operational_state


def test_retention_scan_cursor_upgrade_and_downgrade(tmp_path):
    path = tmp_path / "memory.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    config = _build_config(target, path)
    command.upgrade(config, "v54_preference_exclusions")
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO memory_retention_scan_cursors VALUES ('l1', 100, 1, 'event-a', 1, 1)"
        )
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT summary_id FROM summaries "
            f"WHERE {active_summary_predicate()} AND period_end < 100 "
            "AND (period_end, summary_id) > (1, 'summary-a') "
            "ORDER BY period_end, summary_id LIMIT 10000"
        ).fetchall()
        assert any("idx_summaries_retention_scan" in row[3] for row in plan)
        assert not any("TEMP B-TREE FOR ORDER BY" in row[3] for row in plan)
        clear_portability_operational_state(db)
        assert db.execute("SELECT COUNT(*) FROM memory_retention_scan_cursors").fetchone()[0] == 0
    command.downgrade(config, "v54_preference_exclusions")
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='memory_retention_scan_cursors'"
        ).fetchone() is None


def test_l1_retention_keyset_uses_partial_index(tmp_path):
    path = tmp_path / "l1.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "l1")
    config = _build_config(target, path)
    command.upgrade(config, "v6_cognition_handoffs")
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT timestamp, event_id FROM fact_events "
            "WHERE deleted_at IS NULL AND retention_class=2 AND timestamp < 100 "
            "AND (timestamp, event_id) > (1, 'event-a') "
            "ORDER BY timestamp, event_id LIMIT 10000"
        ).fetchall()
        assert any("idx_fact_events_retention_scan" in row[3] for row in plan)
    command.downgrade(config, "v6_cognition_handoffs")
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE name='idx_fact_events_retention_scan'"
        ).fetchone() is None
