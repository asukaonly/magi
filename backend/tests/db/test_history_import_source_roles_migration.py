"""Source role migration preserves content without guessing historical roles."""

import sqlite3

import pytest
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config


def test_source_roles_upgrade_and_downgrade_preserve_existing_records(tmp_path):
    target = next(target for target in MIGRATION_TARGETS if target.name == "memory_shared")
    path = tmp_path / "memory.db"
    config = _build_config(target, path)
    command.upgrade(config, "v57_entity_identity_tombstones")
    with sqlite3.connect(path) as db:
        db.execute(
            """INSERT INTO history_import_source_records(
                source_record_key, file_fingerprint, source_id, source_name, source_kind,
                parsed_session_key, session_id, session_seq, speaker_id, speaker_name,
                message_key, content, event_at, timestamp_confidence, timestamp_anchor_source,
                calendar_timezone_id, event_id, created_at, speaker_role
            ) VALUES ('r1','f1','s1','archive','chat','session','session',1,'p1','Assistant',
                'm1','Original text',1,'exact','source_timestamp','UTC','e1',2,'other')"""
        )
        before = db.execute("SELECT * FROM history_import_source_records").fetchone()
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        after = db.execute("SELECT * FROM history_import_source_records").fetchone()
        assert after[:-1] == before
        assert after[-1] == "unknown"
        for role in ["user", "assistant", "other", "unknown"]:
            db.execute("UPDATE history_import_source_records SET source_role=?", (role,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE history_import_source_records SET source_role='invented'")
    command.downgrade(config, "v57_entity_identity_tombstones")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM history_import_source_records").fetchone() == before
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT source_role FROM history_import_source_records").fetchone() == (
            "unknown",
        )
