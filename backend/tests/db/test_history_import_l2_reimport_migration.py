"""Regression coverage for explicit history-import L2 replay repair."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config

V47_REVISION = "v47_history_import_deletion_privacy"
V48_REVISION = "v48_history_import_l2_reimport"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def _insert_forget_operation(
    connection: sqlite3.Connection,
    *,
    operation_id: str,
    event_ids: tuple[str, ...],
    reason: str,
    replay_policy: str,
) -> None:
    selector = {
        "event_ids": list(event_ids),
        "block_source_item": False,
        "include_turn_references": False,
        "replay_policy": replay_policy,
    }
    connection.execute(
        """
        INSERT INTO memory_forget_operations(
            operation_id, selector_kind, selector_hash, selector_json,
            reason, status, phase, projection_selection_complete,
            selection_complete, selector_cleanup_complete,
            created_at, updated_at, completed_at
        ) VALUES (?, 'known_events', ?, ?, ?, 'completed', 'completed',
                  1, 1, 1, 1, 1, 1)
        """,
        (
            operation_id,
            f"hash:{operation_id}",
            json.dumps(selector, separators=(",", ":"), sort_keys=True),
            reason,
        ),
    )
    connection.executemany(
        """
        INSERT INTO memory_forget_operation_events(
            operation_id, event_id, was_active, cleanup_status,
            created_at, updated_at
        ) VALUES (?, ?, 1, 'completed', 1, 1)
        """,
        [(operation_id, event_id) for event_id in event_ids],
    )


def _insert_projection_job(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    status: str,
    attempt_count: int = 1,
    batch_attempt_key: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO l2_projection_jobs(
            event_id, source, event_type, status, attempt_count,
            batch_attempt_key, batch_descriptor_json, batch_bound_at,
            created_at, updated_at
        ) VALUES (?, 'history_import', 'history_import.document', ?, ?, ?, ?, ?, 1, 1)
        """,
        (
            event_id,
            status,
            attempt_count,
            batch_attempt_key,
            "{}" if batch_attempt_key is not None else None,
            1 if batch_attempt_key is not None else None,
        ),
    )


def _insert_event_forget_rule(
    connection: sqlite3.Connection,
    *,
    rule_id: str,
    event_ids: tuple[str, ...],
) -> None:
    connection.execute(
        """
        INSERT INTO memory_forget_claim_rules(
            rule_id, target_kind, claim_fingerprint, semantic_fingerprint,
            forget_kind, evidence_fail_closed, created_at
        ) VALUES (?, 'assertion', ?, ?, 'event', 0, 1)
        """,
        (rule_id, f"claim:{rule_id}", f"semantic:{rule_id}"),
    )
    connection.executemany(
        """
        INSERT INTO memory_forget_evidence_events(rule_id, event_id, created_at)
        VALUES (?, ?, 1)
        """,
        [(rule_id, event_id) for event_id in event_ids],
    )


def _insert_history_record(
    connection: sqlite3.Connection,
    *,
    source_record_key: str,
    event_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO history_import_source_records(
            source_record_key, file_fingerprint, source_id, source_name,
            source_kind, parsed_session_key, session_id, session_seq,
            speaker_id, speaker_name, message_key, speaker_role, content,
            event_at, timestamp_confidence, timestamp_anchor_source,
            calendar_timezone_id, meaningful, event_id, created_at
        ) VALUES (?, ?, 'note.md', 'note.md', 'document', 'note.md',
                  'session', 0, '__document_author__', '__document_author__',
                  'document', 'user', 'private text', 1, 'exact',
                  'source_timestamp', 'UTC', 1, ?, 1)
        """,
        (source_record_key, f"fingerprint:{source_record_key}", event_id),
    )


def test_explicit_reimport_migration_releases_only_replayable_l2_state(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V47_REVISION)

    explicit_events = (
        "event-explicit-completed",
        "event-explicit-batch",
        "event-explicit-protected",
        "event-explicit-protected-operation",
    )
    with sqlite3.connect(db_path) as connection:
        _insert_forget_operation(
            connection,
            operation_id="forget-explicit",
            event_ids=explicit_events,
            reason="history_import_deleted",
            replay_policy="explicit_reimport",
        )
        _insert_forget_operation(
            connection,
            operation_id="forget-ordinary",
            event_ids=("event-ordinary", "event-explicit-protected-operation"),
            reason="user_delete_event",
            replay_policy="permanent",
        )
        _insert_forget_operation(
            connection,
            operation_id="forget-history-permanent",
            event_ids=("event-history-permanent",),
            reason="history_import_deleted",
            replay_policy="permanent",
        )

        _insert_projection_job(
            connection,
            event_id="event-explicit-completed",
            status="completed",
        )
        _insert_projection_job(
            connection,
            event_id="event-explicit-batch",
            status="queued",
            attempt_count=2,
            batch_attempt_key="l2pa_shared",
        )
        _insert_projection_job(
            connection,
            event_id="event-batch-peer",
            status="queued",
            attempt_count=2,
            batch_attempt_key="l2pa_shared",
        )
        _insert_projection_job(
            connection,
            event_id="event-ordinary",
            status="completed",
        )
        _insert_projection_job(
            connection,
            event_id="event-history-permanent",
            status="completed",
        )
        _insert_projection_job(
            connection,
            event_id="event-explicit-protected",
            status="completed",
        )
        _insert_projection_job(
            connection,
            event_id="event-explicit-protected-operation",
            status="completed",
        )

        _insert_event_forget_rule(
            connection,
            rule_id="rule-explicit",
            event_ids=("event-explicit-completed",),
        )
        _insert_event_forget_rule(
            connection,
            rule_id="rule-mixed",
            event_ids=("event-explicit-completed", "event-ordinary"),
        )
        _insert_event_forget_rule(
            connection,
            rule_id="rule-history-permanent",
            event_ids=("event-history-permanent",),
        )
        _insert_event_forget_rule(
            connection,
            rule_id="rule-explicit-protected",
            event_ids=("event-explicit-protected",),
        )
        _insert_event_forget_rule(
            connection,
            rule_id="rule-explicit-protected-operation",
            event_ids=("event-explicit-protected-operation",),
        )
        connection.execute(
            """
            INSERT INTO memory_source_event_tombstones(event_id, reason, created_at)
            VALUES ('event-explicit-protected', 'user_delete_event', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                state, created_at, transition_applied_at
            ) VALUES ('correction-forget', 'request-forget', 'user:self',
                      'assertion', 'assertion-forget', 'slot-forget',
                      'claim-forget', 'record_error', '{}', 'active', 1, 1)
            """
        )
        connection.executemany(
            """
            INSERT INTO memory_correction_forget_barriers(
                correction_id, rule_id, created_at
            ) VALUES ('correction-forget', ?, 1)
            """,
            (
                ("rule-explicit",),
                ("rule-explicit-protected",),
                ("rule-explicit-protected-operation",),
                ("rule-mixed",),
                ("rule-history-permanent",),
            ),
        )

        connection.execute(
            """
            INSERT INTO history_import_jobs(
                job_id, source_type, source_fingerprint, source_ids_json,
                included_source_ids_json, detected_kind, status,
                total_records, meaningful_records, imported_count,
                projected_count, self_participant_ids_json, warnings_json,
                quick_ready, created_at, updated_at
            ) VALUES ('active-reimport', 'markdown', 'active-fingerprint',
                      '["note.md"]', '["note.md"]', 'document', 'completed',
                      2, 2, 2, 2, '["__document_author__"]', '[]', 1, 1, 1)
            """
        )
        _insert_history_record(
            connection,
            source_record_key="record-reimport",
            event_id="event-explicit-completed",
        )
        _insert_history_record(
            connection,
            source_record_key="record-unrelated",
            event_id="event-job-unrelated",
        )
        connection.executemany(
            """
            INSERT INTO history_import_job_records(
                job_record_id, job_id, source_record_key, source_order,
                raw_state, projection_state, created_at, updated_at
            ) VALUES (?, 'active-reimport', ?, ?, 'stored', 'projected', 1, 1)
            """,
            (
                ("membership-reimport", "record-reimport", 0),
                ("membership-unrelated", "record-unrelated", 1),
            ),
        )
        connection.commit()

    command.upgrade(config, V48_REVISION)

    with sqlite3.connect(db_path) as connection:
        projection_rows = connection.execute(
            """
            SELECT event_id, status, attempt_count, batch_attempt_key, last_error
            FROM l2_projection_jobs
            ORDER BY event_id
            """
        ).fetchall()
        assert projection_rows == [
            (
                "event-batch-peer",
                "pending",
                1,
                None,
                "projection_batch_invalidated_by_source_forgetting",
            ),
            ("event-explicit-protected", "completed", 1, None, None),
            ("event-explicit-protected-operation", "completed", 1, None, None),
            ("event-history-permanent", "completed", 1, None, None),
            ("event-ordinary", "completed", 1, None, None),
        ]
        assert connection.execute(
            "SELECT rule_id FROM memory_forget_claim_rules ORDER BY rule_id"
        ).fetchall() == [
            ("rule-explicit-protected",),
            ("rule-explicit-protected-operation",),
            ("rule-history-permanent",),
            ("rule-mixed",),
        ]
        assert connection.execute(
            """
            SELECT rule_id, event_id
            FROM memory_forget_evidence_events
            ORDER BY rule_id, event_id
            """
        ).fetchall() == [
            ("rule-explicit-protected", "event-explicit-protected"),
            (
                "rule-explicit-protected-operation",
                "event-explicit-protected-operation",
            ),
            ("rule-history-permanent", "event-history-permanent"),
            ("rule-mixed", "event-ordinary"),
        ]
        assert connection.execute(
            """
            SELECT rule_id
            FROM memory_correction_forget_barriers
            ORDER BY rule_id
            """
        ).fetchall() == [
            ("rule-explicit-protected",),
            ("rule-explicit-protected-operation",),
            ("rule-history-permanent",),
            ("rule-mixed",),
        ]
        assert connection.execute(
            """
            SELECT status, projected_count, quick_ready
            FROM history_import_jobs
            WHERE job_id = 'active-reimport'
            """
        ).fetchone() == ("ready", 1, 1)
        assert connection.execute(
            """
            SELECT job_record_id, projection_state
            FROM history_import_job_records
            WHERE job_id = 'active-reimport'
            ORDER BY job_record_id
            """
        ).fetchall() == [
            ("membership-reimport", "pending"),
            ("membership-unrelated", "projected"),
        ]
        assert connection.execute(
            """
            SELECT job_id
            FROM history_import_jobs
            WHERE deleted_at IS NULL
              AND quick_ready = 1
              AND status IN ('running', 'ready')
            """
        ).fetchall() == [("active-reimport",)]
        assert (
            connection.execute(
                "SELECT name FROM sqlite_temp_master WHERE name LIKE '%_v48'"
            ).fetchall()
            == []
        )
