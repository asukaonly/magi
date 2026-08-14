"""Release stale L2 replay state for explicit history reimports."""

from __future__ import annotations

from alembic import op

revision = "v48_history_import_l2_reimport"
down_revision = "v47_history_import_deletion_privacy"
branch_labels = None
depends_on = None


STATEMENTS = (
    "DROP TABLE IF EXISTS temp.history_import_reimport_events_v48",
    "DROP TABLE IF EXISTS temp.history_import_reimport_batches_v48",
    "DROP TABLE IF EXISTS temp.history_import_reimport_rules_v48",
    "DROP TABLE IF EXISTS temp.history_import_reimport_jobs_v48",
    "CREATE TEMP TABLE history_import_reimport_events_v48("
    "event_id TEXT PRIMARY KEY NOT NULL)",
    """
INSERT OR IGNORE INTO history_import_reimport_events_v48(event_id)
SELECT DISTINCT events.event_id
FROM memory_forget_operation_events AS events
JOIN memory_forget_operations AS operations
  ON operations.operation_id = events.operation_id
WHERE operations.selector_kind = 'known_events'
  AND operations.reason = 'history_import_deleted'
  AND json_extract(operations.selector_json, '$.replay_policy') = 'explicit_reimport'
  AND NOT EXISTS (
      SELECT 1
      FROM memory_source_event_tombstones AS tombstones
      WHERE tombstones.event_id = events.event_id
  )
  AND NOT EXISTS (
      SELECT 1
      FROM memory_forget_operation_events AS retained_events
      JOIN memory_forget_operations AS retained_operations
        ON retained_operations.operation_id = retained_events.operation_id
      WHERE retained_events.event_id = events.event_id
        AND NOT (
            retained_operations.selector_kind = 'known_events'
            AND retained_operations.reason = 'history_import_deleted'
            AND json_extract(
                retained_operations.selector_json,
                '$.replay_policy'
            ) = 'explicit_reimport'
        )
  )
""".strip(),
    "CREATE TEMP TABLE history_import_reimport_batches_v48("
    "batch_attempt_key TEXT PRIMARY KEY NOT NULL)",
    """
INSERT OR IGNORE INTO history_import_reimport_batches_v48(batch_attempt_key)
SELECT DISTINCT jobs.batch_attempt_key
FROM l2_projection_jobs AS jobs
JOIN history_import_reimport_events_v48 AS events
  ON events.event_id = jobs.event_id
WHERE jobs.status IN ('queued', 'running')
  AND jobs.batch_attempt_key IS NOT NULL
""".strip(),
    """
UPDATE l2_projection_jobs
SET status = 'pending',
    attempt_count = CASE
        WHEN replay_requested = 1 THEN 0
        ELSE MAX(attempt_count - 1, 0)
    END,
    lease_token = NULL,
    lease_heartbeat_at = NULL,
    batch_attempt_key = NULL,
    batch_descriptor_json = NULL,
    batch_bound_at = NULL,
    next_retry_at = NULL,
    terminal_at = NULL,
    replay_requested = 0,
    claimed_by = NULL,
    claimed_at = NULL,
    started_at = NULL,
    completed_at = NULL,
    last_error = 'projection_batch_invalidated_by_source_forgetting',
    updated_at = CAST(strftime('%s', 'now') AS REAL)
WHERE batch_attempt_key IN (
        SELECT batch_attempt_key FROM history_import_reimport_batches_v48
    )
  AND event_id NOT IN (
        SELECT event_id FROM history_import_reimport_events_v48
    )
  AND status IN ('queued', 'running')
""".strip(),
    """
DELETE FROM l2_projection_jobs
WHERE event_id IN (SELECT event_id FROM history_import_reimport_events_v48)
""".strip(),
    "CREATE TEMP TABLE history_import_reimport_rules_v48("
    "rule_id TEXT PRIMARY KEY NOT NULL)",
    """
INSERT OR IGNORE INTO history_import_reimport_rules_v48(rule_id)
SELECT DISTINCT rules.rule_id
FROM memory_forget_claim_rules AS rules
JOIN memory_forget_evidence_events AS evidence
  ON evidence.rule_id = rules.rule_id
JOIN history_import_reimport_events_v48 AS events
  ON events.event_id = evidence.event_id
WHERE rules.forget_kind = 'event'
""".strip(),
    """
DELETE FROM memory_forget_evidence_events
WHERE rule_id IN (SELECT rule_id FROM history_import_reimport_rules_v48)
  AND event_id IN (SELECT event_id FROM history_import_reimport_events_v48)
""".strip(),
    """
DELETE FROM memory_correction_forget_barriers
WHERE rule_id IN (SELECT rule_id FROM history_import_reimport_rules_v48)
  AND NOT EXISTS (
      SELECT 1
      FROM memory_forget_evidence_events AS evidence
      WHERE evidence.rule_id = memory_correction_forget_barriers.rule_id
  )
""".strip(),
    """
DELETE FROM memory_forget_claim_rules
WHERE forget_kind = 'event'
  AND rule_id IN (SELECT rule_id FROM history_import_reimport_rules_v48)
  AND NOT EXISTS (
      SELECT 1
      FROM memory_forget_evidence_events AS evidence
      WHERE evidence.rule_id = memory_forget_claim_rules.rule_id
  )
""".strip(),
    "CREATE TEMP TABLE history_import_reimport_jobs_v48("
    "job_id TEXT PRIMARY KEY NOT NULL)",
    """
INSERT OR IGNORE INTO history_import_reimport_jobs_v48(job_id)
SELECT DISTINCT memberships.job_id
FROM history_import_job_records AS memberships
JOIN history_import_jobs AS jobs
  ON jobs.job_id = memberships.job_id
JOIN history_import_source_records AS source
  ON source.source_record_key = memberships.source_record_key
JOIN history_import_reimport_events_v48 AS events
  ON events.event_id = source.event_id
WHERE jobs.deleted_at IS NULL
  AND jobs.status != 'preview_ready'
  AND memberships.raw_state = 'stored'
  AND source.speaker_role = 'user'
""".strip(),
    """
UPDATE history_import_job_records
SET projection_state = 'pending',
    updated_at = CAST(strftime('%s', 'now') AS REAL)
WHERE job_id IN (SELECT job_id FROM history_import_reimport_jobs_v48)
  AND raw_state = 'stored'
  AND source_record_key IN (
      SELECT source.source_record_key
      FROM history_import_source_records AS source
      JOIN history_import_reimport_events_v48 AS events
        ON events.event_id = source.event_id
      WHERE source.speaker_role = 'user'
  )
""".strip(),
    """
UPDATE history_import_jobs
SET projected_count = (
        SELECT COUNT(*)
        FROM history_import_job_records AS memberships
        WHERE memberships.job_id = history_import_jobs.job_id
          AND memberships.projection_state = 'projected'
    ),
    status = CASE WHEN quick_ready = 1 THEN 'ready' ELSE status END,
    error_text = CASE WHEN quick_ready = 1 THEN NULL ELSE error_text END,
    updated_at = CAST(strftime('%s', 'now') AS REAL)
WHERE job_id IN (SELECT job_id FROM history_import_reimport_jobs_v48)
""".strip(),
    "DROP TABLE history_import_reimport_jobs_v48",
    "DROP TABLE history_import_reimport_rules_v48",
    "DROP TABLE history_import_reimport_batches_v48",
    "DROP TABLE history_import_reimport_events_v48",
)
SCHEMA_SQL = ";\n".join(STATEMENTS) + ";"


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def schema_sql_for_fresh_database() -> str:
    """Return the release-time repair for fresh databases."""

    return SCHEMA_SQL


def downgrade() -> None:
    """Released replay state and rescheduled projections are irreversible."""


__all__ = [
    "SCHEMA_SQL",
    "STATEMENTS",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
