from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V24_REVISION = "v24_entity_name_evidence"
V25_REVISION = "v25_daily_mood_source_events"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def test_daily_mood_lineage_migration_drops_unattributable_legacy_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V24_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO daily_mood_aggregate(
                day_local_date, dominant_valence, volatility_score,
                state_curve_compact, event_count, computed_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("2026-05-17", "warm", 0.2, "[0.5]", 4, 1.0),
                ("2026-05-18", "neutral", 0.0, "[]", 0, 2.0),
            ],
        )
        connection.commit()

    command.upgrade(config, V25_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V25_REVISION,
        )
        assert "source_event_ids" in {
            row[1] for row in connection.execute("PRAGMA table_info(daily_mood_aggregate)")
        }
        assert connection.execute("SELECT COUNT(*) FROM daily_mood_aggregate").fetchone() == (0,)


@pytest.mark.parametrize("retained", [False, True])
def test_daily_mood_lineage_guards_retained_projection_and_allows_empty_downgrade(
    tmp_path: Path, retained: bool
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    if not retained:
        command.upgrade(config, V25_REVISION)
        command.downgrade(config, V24_REVISION)

        with sqlite3.connect(db_path) as connection:
            assert "source_event_ids" not in {
                row[1] for row in connection.execute("PRAGMA table_info(daily_mood_aggregate)")
            }
        return

    command.upgrade(config, V25_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            INSERT INTO daily_mood_aggregate(
                day_local_date, dominant_valence, volatility_score,
                state_curve_compact, event_count, source_event_ids, computed_at
            ) VALUES ('2026-05-17', 'warm', 0.2, '[0.5]', 1, '["event-one"]', 1)
            """)
        connection.commit()

    tables = ["daily_mood_aggregate"]
    with sqlite3.connect(db_path) as connection:
        before = {
            name: connection.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()
            for name in tables
        }

    with pytest.raises(RuntimeError, match="retained data"):
        command.downgrade(config, V24_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V25_REVISION,
        )

    with sqlite3.connect(db_path) as connection:
        assert {
            name: connection.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()
            for name in tables
        } == before
