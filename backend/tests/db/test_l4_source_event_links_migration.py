from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V21_REVISION = "v21_source_event_forgetting"
V22_REVISION = "v22_l4_source_event_links"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def test_l4_source_event_links_backfill_rows_and_traces(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V21_REVISION)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO procedural_skills(
                skill_id, skill_name, skill_category, skill_type,
                total_attempts, source_event_ids, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "skill-existing",
                "browser.open",
                "tool",
                "external_tool",
                200,
                json.dumps(["  event-parent  ", "event-shared"]),
                10.0,
                11.0,
            ),
        )
        connection.execute(
            """
            INSERT INTO procedural_skills(
                skill_id, skill_name, skill_category, skill_type,
                total_attempts, optimized_prompt, source_event_ids,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "skill-complete",
                "editor.save",
                "tool",
                "external_tool",
                2,
                "Keep this fully attributable strategy",
                json.dumps(["event-complete-one", "event-complete-two"]),
                10.0,
                11.0,
            ),
        )
        connection.execute("""
            INSERT INTO l4_execution_traces(
                trace_id, skill_id, event_id, success, created_at
            ) VALUES ('trace-existing', 'skill-existing', '  event-trace  ', 1, 12)
            """)
        connection.execute("""
            INSERT INTO l4_skill_chunks(
                chunk_id, skill_id, chunk_index, chunk_text,
                char_start, char_end, token_estimate, created_at, updated_at
            ) VALUES ('chunk-existing', 'skill-existing', 0, 'private legacy skill',
                      0, 20, 4, 12, 12)
            """)
        connection.execute("""
            INSERT INTO l4_skills_fts(skill_id, content)
            VALUES ('skill-existing', 'private legacy skill')
            """)
        connection.commit()

    command.upgrade(config, V22_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V22_REVISION,
        )
        assert (
            connection.execute("""
            SELECT skill_id, event_id
            FROM l4_skill_event_links
            ORDER BY event_id
            """).fetchall()
            == [
                ("skill-complete", "event-complete-one"),
                ("skill-complete", "event-complete-two"),
                ("skill-existing", "event-parent"),
                ("skill-existing", "event-shared"),
                ("skill-existing", "event-trace"),
            ]
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            connection.execute("""
            SELECT skill_name, skill_category, optimized_prompt,
                   source_event_ids, deleted_at
            FROM procedural_skills WHERE skill_id = 'skill-existing'
            """).fetchone()
            == (
                "__legacy_unattributed__:skill-existing",
                "__legacy_unattributed__",
                None,
                "[]",
                11.0,
            )
        )
        assert connection.execute("SELECT COUNT(*) FROM l4_execution_traces").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM l4_skill_chunks").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM l4_skills_fts").fetchone() == (0,)
        assert connection.execute("""
            SELECT optimized_prompt, deleted_at
            FROM procedural_skills WHERE skill_id = 'skill-complete'
            """).fetchone() == ("Keep this fully attributable strategy", None)


def test_l4_source_event_links_empty_migration_round_trips(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V21_REVISION)
    command.upgrade(config, V22_REVISION)
    command.downgrade(config, V21_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V21_REVISION,
        )
        assert connection.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'l4_skill_event_links'
            """).fetchone() is None

    command.upgrade(config, V22_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V22_REVISION,
        )
        assert connection.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'l4_skill_event_links'
            """).fetchone() == (1,)


def test_l4_source_event_links_refuse_to_drop_retained_lineage(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V21_REVISION)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO procedural_skills(
                skill_id, skill_name, skill_category, skill_type,
                source_event_ids, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "skill-retained",
                "browser.open",
                "tool",
                "external_tool",
                json.dumps(["event-retained"]),
                10.0,
                11.0,
            ),
        )
        connection.commit()

    command.upgrade(config, V22_REVISION)

    with pytest.raises(
        RuntimeError,
        match="Cannot downgrade L4 source-event links while retained data exists",
    ):
        command.downgrade(config, V21_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V22_REVISION,
        )
        assert connection.execute(
            "SELECT skill_id, event_id FROM l4_skill_event_links"
        ).fetchall() == [("skill-retained", "event-retained")]
