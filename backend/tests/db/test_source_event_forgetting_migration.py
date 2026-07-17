from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V20_REVISION = "v20_identity_rekey_indexes"
V21_REVISION = "v21_source_event_forgetting"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def test_source_event_forgetting_migration_preserves_governance_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V20_REVISION)

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("""
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                state, created_at
            ) VALUES ('correction-existing', 'request-existing', 'user:u1',
                      'assertion', 'assertion-existing', 'slot-existing',
                      'claim-existing', 'record_error', '{}', 'active', 10)
            """)
        connection.execute("""
            INSERT INTO memory_forget_claim_rules(
                rule_id, target_kind, claim_fingerprint, semantic_fingerprint,
                forget_kind, evidence_fail_closed, created_at
            ) VALUES ('rule-existing', 'assertion', 'claim-existing',
                      'semantic-existing', 'entity', 0, 11)
            """)
        connection.execute("""
            INSERT INTO memory_forget_evidence_events(rule_id, event_id, created_at)
            VALUES ('rule-existing', 'event-existing', 12)
            """)
        connection.execute("""
            INSERT INTO memory_correction_forget_barriers(
                correction_id, rule_id, created_at
            ) VALUES ('correction-existing', 'rule-existing', 13)
            """)
        connection.commit()

    command.upgrade(config, V21_REVISION)

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V21_REVISION,
        )
        assert connection.execute(
            "SELECT rule_id, forget_kind FROM memory_forget_claim_rules"
        ).fetchall() == [("rule-existing", "entity")]
        assert connection.execute(
            "SELECT rule_id, event_id FROM memory_forget_evidence_events"
        ).fetchall() == [("rule-existing", "event-existing")]
        assert connection.execute(
            "SELECT correction_id, rule_id FROM memory_correction_forget_barriers"
        ).fetchall() == [("correction-existing", "rule-existing")]
        connection.execute("""
            INSERT INTO memory_forget_claim_rules(
                rule_id, target_kind, claim_fingerprint, semantic_fingerprint,
                forget_kind, evidence_fail_closed, created_at
            ) VALUES ('rule-event', 'edge', 'claim-event', 'semantic-event',
                      'event', 0, 20)
            """)
        connection.execute("""
            INSERT INTO memory_source_event_tombstones(event_id, reason, created_at)
            VALUES ('event-forgotten', 'user_delete_event', 20)
            """)
        connection.execute("""
            UPDATE memory_corrections
            SET transition_cancel_reason = 'forget_event'
            WHERE correction_id = 'correction-existing'
            """)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        connection.commit()

    with pytest.raises(RuntimeError, match="retained event-forget data"):
        command.downgrade(config, V20_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V21_REVISION,
        )


def test_source_event_forgetting_empty_migration_round_trips(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V20_REVISION)
    command.upgrade(config, V21_REVISION)
    command.downgrade(config, V20_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V20_REVISION,
        )
        assert connection.execute("""
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'memory_source_event_tombstones'
            """).fetchone() is None
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("""
                INSERT INTO memory_forget_claim_rules(
                    rule_id, target_kind, claim_fingerprint, semantic_fingerprint,
                    forget_kind, evidence_fail_closed, created_at
                ) VALUES ('rule-event', 'edge', 'claim-event', 'semantic-event',
                          'event', 0, 20)
                """)
