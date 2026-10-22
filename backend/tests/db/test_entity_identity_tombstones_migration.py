"""Explicit identity erasure remains distinguishable from ordinary catalog damage."""

import json
import sqlite3

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config


def test_identity_tombstone_upgrade_backfill_and_roundtrip(tmp_path):
    path = tmp_path / "memory.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    config = _build_config(target, path)
    command.upgrade(config, "v56_l0_outcome_receipts")
    with sqlite3.connect(path) as db:
        for entity, ready in (("forgotten", 1), ("not-activated", 0)):
            db.execute(
                """INSERT INTO memory_forget_operations(
                    operation_id,selector_kind,selector_hash,selector_json,reason,
                    execution_ready,created_at,updated_at
                ) VALUES (?, 'entity', ?, ?, 'user_request', ?, 1, 1)""",
                (entity, entity, json.dumps({"entity_id": entity}), ready),
            )
        db.execute(
            "INSERT INTO entity_source_bindings VALUES ('source', 'hash', 'ordinary-damage')"
        )
        db.execute("INSERT INTO entity_identity_redirects VALUES ('old','middle','merge-1')")
        db.execute(
            "INSERT INTO entity_identity_redirects VALUES ('middle','missing-target','merge-2')"
        )
        db.execute("INSERT INTO entity_identity_redirects VALUES ('other','alive','merge-3')")
        db.execute(
            "INSERT INTO entity_catalog(entity_id,canonical_name,entity_type,created_at,updated_at) VALUES ('alive','Private display name','software',1,1)"
        )
    for _ in range(2):
        command.upgrade(config, "head")
        with sqlite3.connect(path) as db:
            assert db.execute(
                "SELECT entity_id,reason,operation_id FROM entity_identity_tombstones ORDER BY entity_id"
            ).fetchall() == [
                ("forgotten", "forgotten", "forgotten"),
                ("missing-target", "missing_redirect_target", "merge-2"),
            ]
            assert db.execute("SELECT entity_id FROM entity_source_bindings").fetchall() == [
                ("ordinary-damage",)
            ]
            plan = db.execute(
                "EXPLAIN QUERY PLAN SELECT 1 FROM entity_source_bindings WHERE entity_id='ordinary-damage'"
            ).fetchall()
            assert any("idx_entity_source_bindings_entity" in row[3] for row in plan)
            assert [
                row[1] for row in db.execute("PRAGMA table_info(entity_identity_tombstones)")
            ] == ["entity_id", "reason", "operation_id", "created_at"]
        command.downgrade(config, "v56_l0_outcome_receipts")
        with sqlite3.connect(path) as db:
            assert (
                db.execute(
                    "SELECT name FROM sqlite_master WHERE name='entity_identity_tombstones'"
                ).fetchone()
                is None
            )
