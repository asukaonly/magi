from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V23_REVISION = "v23_l0_tactic_source_tombstones"
V24_REVISION = "v24_entity_name_evidence"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def test_entity_name_evidence_backfills_only_attributable_names(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V23_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            INSERT INTO entity_catalog(
                entity_id, canonical_name, entity_type, created_at, updated_at
            ) VALUES ('place:shanghai', 'Shanghai', 'place', 1, 2)
            """)
        connection.execute("""
            INSERT INTO entity_catalog(
                entity_id, canonical_name, entity_type, created_at, updated_at
            ) VALUES ('person:manual', 'Manual canonical', 'person', 1, 2)
            """)
        connection.executemany(
            """
            INSERT INTO entity_aliases(
                entity_id, alias_text, normalized_alias, confidence,
                created_at, updated_at
            ) VALUES ('place:shanghai', ?, ?, ?, 1, 2)
            """,
            [
                ("Shanghai", "shanghai", 0.9),
                ("Independent label", "independent label", 1.0),
            ],
        )
        connection.execute(
            """
            INSERT INTO entity_mentions(
                mention_text, normalized_surface, entity_type,
                evidence_event_ids, evidence_text, resolved_entity_id,
                confidence, created_at
            ) VALUES (?, ?, 'place', ?, ?, 'place:shanghai', 0.8, 3)
            """,
            (
                "Shanghai",
                "Shanghai",
                json.dumps(["event-one", "event-two"]),
                "Shanghai",
            ),
        )
        connection.execute("""
            INSERT INTO entity_mentions(
                mention_text, normalized_surface, entity_type,
                evidence_event_ids, evidence_text, resolved_entity_id,
                confidence, created_at
            ) VALUES (
                'Different source mention', 'different source mention', 'person',
                '["event-manual-neighbor"]', 'Different source mention',
                'person:manual', 0.8, 3
            )
            """)
        connection.commit()

    command.upgrade(config, V24_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V24_REVISION,
        )
        assert connection.execute("""
            SELECT canonical_name_is_independent
            FROM entity_catalog WHERE entity_id = 'place:shanghai'
            """).fetchone() == (0,)
        assert connection.execute("""
            SELECT canonical_name_is_independent
            FROM entity_catalog WHERE entity_id = 'person:manual'
            """).fetchone() == (0,)
        assert connection.execute("""
            SELECT normalized_alias, is_independent
            FROM entity_aliases ORDER BY normalized_alias
            """).fetchall() == [("independent label", 0), ("shanghai", 0)]
        assert (
            connection.execute("""
            SELECT name_kind, normalized_name, event_id
            FROM entity_name_evidence
            ORDER BY name_kind, normalized_name, event_id
            """).fetchall()
            == [
                ("alias", "shanghai", "event-one"),
                ("alias", "shanghai", "event-two"),
                ("canonical", "shanghai", "event-one"),
                ("canonical", "shanghai", "event-two"),
            ]
        )


def test_entity_name_evidence_normalizes_unicode_alias_and_legacy_event_id(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V23_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            INSERT INTO entity_catalog(
                entity_id, canonical_name, entity_type, created_at, updated_at
            ) VALUES ('person:unicode', 'Retained person', 'person', 1, 2)
            """)
        connection.executemany(
            """
            INSERT INTO entity_aliases(
                entity_id, alias_text, normalized_alias, confidence,
                created_at, updated_at
            ) VALUES ('person:unicode', ?, ?, 0.9, 1, 2)
            """,
            [
                ("Straße", "strasse"),
                ("Hidden alias", "hidden alias"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO entity_mentions(
                mention_text, normalized_surface, entity_type,
                evidence_event_ids, evidence_text, resolved_entity_id,
                confidence, created_at
            ) VALUES (?, ?, 'person', ?, ?, 'person:unicode', 0.8, 3)
            """,
            [
                ("Straße", "Straße", '["  event-unicode  "]', "Straße"),
                (
                    "Hidden alias",
                    "Hidden alias",
                    '["  event-tombstoned  "]',
                    "Hidden alias",
                ),
            ],
        )
        connection.execute("""
            INSERT INTO memory_source_event_tombstones(event_id, reason, created_at)
            VALUES ('event-tombstoned', 'user_delete_event', 4)
            """)
        connection.commit()

    command.upgrade(config, V24_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute("""
            SELECT name_kind, normalized_name, display_name, event_id
            FROM entity_name_evidence
            ORDER BY normalized_name
            """).fetchall()
            == [
                ("alias", "strasse", "Straße", "event-unicode"),
            ]
        )


def test_entity_name_evidence_empty_migration_round_trips(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V24_REVISION)
    command.downgrade(config, V23_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'entity_name_evidence'
            """).fetchone() is None
        assert "is_independent" not in {
            row[1] for row in connection.execute("PRAGMA table_info(entity_aliases)")
        }


def test_entity_name_evidence_refuses_to_drop_retained_lineage(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V24_REVISION)
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            INSERT INTO entity_catalog(
                entity_id, canonical_name, entity_type,
                canonical_name_is_independent, created_at, updated_at
            ) VALUES ('topic:one', 'One', 'topic', 0, 1, 1)
            """)
        connection.execute("""
            INSERT INTO entity_name_evidence(
                entity_id, name_kind, normalized_name, display_name,
                event_id, confidence, created_at, updated_at
            ) VALUES ('topic:one', 'canonical', 'one', 'One', 'event-one', 1, 1, 1)
            """)
        connection.commit()

    with pytest.raises(RuntimeError, match="retained data"):
        command.downgrade(config, V23_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V24_REVISION,
        )
