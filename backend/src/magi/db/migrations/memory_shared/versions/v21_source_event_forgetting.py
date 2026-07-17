"""Add durable source-event forgetting and event-scoped claim governance.

Revision ID: v21_source_event_forgetting
Revises: v20_identity_rekey_indexes
"""

from __future__ import annotations

import sqlite3

from alembic import op

revision = "v21_source_event_forgetting"
down_revision = "v20_identity_rekey_indexes"
branch_labels = None
depends_on = None


_EVENT_RULE_TABLES_SQL = """
CREATE TABLE memory_forget_claim_rules_v21 (
    rule_id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('assertion', 'edge')),
    claim_fingerprint TEXT NOT NULL,
    semantic_fingerprint TEXT NOT NULL,
    forget_kind TEXT NOT NULL CHECK(forget_kind IN ('entity', 'time_range', 'event')),
    effective_from REAL,
    effective_to REAL,
    evidence_fail_closed INTEGER NOT NULL DEFAULT 0 CHECK(
        evidence_fail_closed IN (0, 1)
    ),
    created_at REAL NOT NULL,
    CHECK(
        (forget_kind = 'entity' AND effective_from IS NULL AND effective_to IS NULL)
        OR (
            forget_kind = 'time_range'
            AND effective_from IS NOT NULL
            AND effective_to IS NOT NULL
            AND effective_to >= effective_from
        )
        OR (forget_kind = 'event' AND effective_from IS NULL AND effective_to IS NULL)
    )
);
CREATE TABLE memory_forget_evidence_events_v21 (
    rule_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(rule_id, event_id),
    FOREIGN KEY(rule_id) REFERENCES memory_forget_claim_rules_v21(rule_id)
        ON DELETE CASCADE
);
CREATE TABLE memory_correction_forget_barriers_v21 (
    correction_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(correction_id, rule_id),
    FOREIGN KEY(correction_id) REFERENCES memory_corrections(correction_id)
        ON DELETE CASCADE,
    FOREIGN KEY(rule_id) REFERENCES memory_forget_claim_rules_v21(rule_id)
        ON DELETE CASCADE
);
INSERT INTO memory_forget_claim_rules_v21
SELECT * FROM memory_forget_claim_rules;
INSERT INTO memory_forget_evidence_events_v21
SELECT * FROM memory_forget_evidence_events;
INSERT INTO memory_correction_forget_barriers_v21
SELECT * FROM memory_correction_forget_barriers;
DROP TABLE memory_correction_forget_barriers;
DROP TABLE memory_forget_evidence_events;
DROP TABLE memory_forget_claim_rules;
ALTER TABLE memory_forget_claim_rules_v21 RENAME TO memory_forget_claim_rules;
ALTER TABLE memory_forget_evidence_events_v21 RENAME TO memory_forget_evidence_events;
ALTER TABLE memory_correction_forget_barriers_v21
    RENAME TO memory_correction_forget_barriers;
CREATE INDEX idx_memory_forget_claim_rules_lookup
    ON memory_forget_claim_rules(
        target_kind, semantic_fingerprint, forget_kind,
        effective_from, effective_to
    );
CREATE INDEX idx_memory_forget_evidence_event
    ON memory_forget_evidence_events(event_id, rule_id);
CREATE INDEX idx_memory_correction_forget_barrier_rule
    ON memory_correction_forget_barriers(rule_id, correction_id);
"""


_LEGACY_RULE_TABLES_SQL = """
CREATE TABLE memory_forget_claim_rules_v20 (
    rule_id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('assertion', 'edge')),
    claim_fingerprint TEXT NOT NULL,
    semantic_fingerprint TEXT NOT NULL,
    forget_kind TEXT NOT NULL CHECK(forget_kind IN ('entity', 'time_range')),
    effective_from REAL,
    effective_to REAL,
    evidence_fail_closed INTEGER NOT NULL DEFAULT 0 CHECK(
        evidence_fail_closed IN (0, 1)
    ),
    created_at REAL NOT NULL,
    CHECK(
        (forget_kind = 'entity' AND effective_from IS NULL AND effective_to IS NULL)
        OR (
            forget_kind = 'time_range'
            AND effective_from IS NOT NULL
            AND effective_to IS NOT NULL
            AND effective_to >= effective_from
        )
    )
);
CREATE TABLE memory_forget_evidence_events_v20 (
    rule_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(rule_id, event_id),
    FOREIGN KEY(rule_id) REFERENCES memory_forget_claim_rules_v20(rule_id)
        ON DELETE CASCADE
);
CREATE TABLE memory_correction_forget_barriers_v20 (
    correction_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(correction_id, rule_id),
    FOREIGN KEY(correction_id) REFERENCES memory_corrections(correction_id)
        ON DELETE CASCADE,
    FOREIGN KEY(rule_id) REFERENCES memory_forget_claim_rules_v20(rule_id)
        ON DELETE CASCADE
);
INSERT INTO memory_forget_claim_rules_v20
SELECT * FROM memory_forget_claim_rules;
INSERT INTO memory_forget_evidence_events_v20
SELECT * FROM memory_forget_evidence_events;
INSERT INTO memory_correction_forget_barriers_v20
SELECT * FROM memory_correction_forget_barriers;
DROP TABLE memory_correction_forget_barriers;
DROP TABLE memory_forget_evidence_events;
DROP TABLE memory_forget_claim_rules;
ALTER TABLE memory_forget_claim_rules_v20 RENAME TO memory_forget_claim_rules;
ALTER TABLE memory_forget_evidence_events_v20 RENAME TO memory_forget_evidence_events;
ALTER TABLE memory_correction_forget_barriers_v20
    RENAME TO memory_correction_forget_barriers;
CREATE INDEX idx_memory_forget_claim_rules_lookup
    ON memory_forget_claim_rules(
        target_kind, semantic_fingerprint, forget_kind,
        effective_from, effective_to
    );
CREATE INDEX idx_memory_forget_evidence_event
    ON memory_forget_evidence_events(event_id, rule_id);
CREATE INDEX idx_memory_correction_forget_barrier_rule
    ON memory_correction_forget_barriers(rule_id, correction_id);
"""


SCHEMA_SQL = f"""
ALTER TABLE memory_corrections ADD COLUMN transition_cancel_reason_v21 TEXT CHECK(
    transition_cancel_reason_v21 IN ('forget_entity', 'forget_time_range', 'forget_event')
);
UPDATE memory_corrections
SET transition_cancel_reason_v21 = transition_cancel_reason;
ALTER TABLE memory_corrections DROP COLUMN transition_cancel_reason;
ALTER TABLE memory_corrections
    RENAME COLUMN transition_cancel_reason_v21 TO transition_cancel_reason;

{_EVENT_RULE_TABLES_SQL}

CREATE TABLE memory_source_event_tombstones (
    event_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX idx_memory_source_event_tombstones_created
    ON memory_source_event_tombstones(created_at, event_id);
"""


DOWNGRADE_SQL = f"""
DROP INDEX IF EXISTS idx_memory_source_event_tombstones_created;
DROP TABLE memory_source_event_tombstones;

{_LEGACY_RULE_TABLES_SQL}

ALTER TABLE memory_corrections ADD COLUMN transition_cancel_reason_v20 TEXT CHECK(
    transition_cancel_reason_v20 IN ('forget_entity', 'forget_time_range')
);
UPDATE memory_corrections
SET transition_cancel_reason_v20 = transition_cancel_reason;
ALTER TABLE memory_corrections DROP COLUMN transition_cancel_reason;
ALTER TABLE memory_corrections
    RENAME COLUMN transition_cancel_reason_v20 TO transition_cancel_reason;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a newly created shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v21_source_event_forgetting")
    try:
        _execute_script(connection, SCHEMA_SQL)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v21_source_event_forgetting")
        connection.execute("RELEASE SAVEPOINT v21_source_event_forgetting")
        raise
    connection.execute("RELEASE SAVEPOINT v21_source_event_forgetting")


def downgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v21_source_event_forgetting_down")
    try:
        retained = connection.execute("""
            SELECT
                (SELECT COUNT(*) FROM memory_source_event_tombstones)
              + (SELECT COUNT(*) FROM memory_forget_claim_rules WHERE forget_kind = 'event')
              + (SELECT COUNT(*) FROM memory_corrections
                 WHERE transition_cancel_reason = 'forget_event')
            """).fetchone()
        if retained is not None and int(retained[0]) > 0:
            raise RuntimeError(
                "Cannot downgrade source-event forgetting with retained event-forget data"
            )
        _execute_script(connection, DOWNGRADE_SQL)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v21_source_event_forgetting_down")
        connection.execute("RELEASE SAVEPOINT v21_source_event_forgetting_down")
        raise
    connection.execute("RELEASE SAVEPOINT v21_source_event_forgetting_down")


def _execute_script(connection: object, script: str) -> None:
    pending = ""
    for line in script.splitlines():
        pending = f"{pending}{line}\n"
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                connection.execute(statement)  # type: ignore[attr-defined]
            pending = ""
    if pending.strip():
        raise RuntimeError("Incomplete source-event forgetting migration statement")


__all__ = [
    "DOWNGRADE_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
