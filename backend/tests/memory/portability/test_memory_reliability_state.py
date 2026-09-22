"""Durable cognition obligations and exclusion effects survive backup inspection."""

from pathlib import Path
import sqlite3

import pytest

from magi.memory.portability.backup import build_memory_backup
from magi.memory.portability.preflight import inspect_memory_backup, load_restore_candidate
from magi.memory.portability.storage import create_memory_snapshot, discard_snapshot
from magi.utils.runtime import RuntimePaths

from ._helpers import FakeUnifiedMemory, migrate_memory_databases, seed_memory


@pytest.mark.asyncio
async def test_backup_preserves_cognition_handoffs_and_preference_exclusion_effects(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    migrate_memory_databases(paths)
    seed_memory(paths)
    (paths.memory_dir / "archive").mkdir(mode=0o700)
    with sqlite3.connect(paths.l1_memory_db_path) as connection:
        connection.execute(
            """
            INSERT INTO fact_events(
                event_id, timestamp, created_at, event_type, source, memory_domain,
                cognition_eligible, content, author_type, content_type
            ) VALUES ('pending-cognition', 2, 2, 'manual_entry', 'manual_entry', 1,
                      1, 'I no longer like jazz.', 1, 1)
            """
        )
        connection.execute(
            """
            UPDATE l1_cognition_handoffs
            SET available_at = 20, attempt_count = 2, last_error = 'RuntimeError'
            WHERE event_id = 'pending-cognition'
            """
        )
    with sqlite3.connect(paths.memory_db_path) as connection:
        connection.execute(
            """
            INSERT INTO knowledge_graph(
                triple_id, subject_id, subject_type, predicate, object_id, object_type,
                evidence_event_ids, first_observed_at, last_observed_at, created_at,
                updated_at, status, valid_to
            ) VALUES ('old-preference', 'user:self', 'user', 'LIKES', 'jazz', 'concept',
                      '["event-1"]', 1, 1, 1, 2, 'superseded', 2)
            """
        )
        connection.execute(
            """
            INSERT INTO l2_preference_exclusion_effects(
                target_kind, target_id, subject_id, before_status, before_valid_to,
                effective_at, applied_at
            ) VALUES ('relationship', 'old-preference', 'user:self', 'active', NULL, 2, 3)
            """
        )
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=FakeUnifiedMemory(),
        include_l0=False,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    try:
        backup_path, _manifest = build_memory_backup(
            snapshot=snapshot,
            output_directory=output_dir,
            encryption="none",
            password=None,
        )
    finally:
        discard_snapshot(snapshot)

    inspection = inspect_memory_backup(
        source_path=backup_path,
        password=None,
        runtime_paths=paths,
        archive_target=paths.memory_dir / "archive",
    )
    candidate_root, _metadata, _manifest = load_restore_candidate(
        runtime_paths=paths,
        candidate_id=str(inspection.candidate_id),
        fingerprint=inspection.fingerprint,
    )
    database_dir = candidate_root / "payload" / "databases"
    with sqlite3.connect(database_dir / "l1_events.db") as connection:
        assert connection.execute(
            "SELECT event_id, created_at, available_at, attempt_count, last_error "
            "FROM l1_cognition_handoffs"
        ).fetchall() == [("pending-cognition", 2, 20, 2, "RuntimeError")]
    with sqlite3.connect(database_dir / "memory.db") as connection:
        assert connection.execute(
            "SELECT target_kind, target_id, subject_id, before_status, before_valid_to, "
            "effective_at, applied_at FROM l2_preference_exclusion_effects"
        ).fetchall() == [("relationship", "old-preference", "user:self", "active", None, 2, 3)]
        assert connection.execute(
            "SELECT status, valid_to FROM knowledge_graph WHERE triple_id = 'old-preference'"
        ).fetchone() == ("superseded", 2)
