"""Create governed pre-materialization review truth."""

from __future__ import annotations

from alembic import op

revision = "v44_l2_pending_reviews"
down_revision = "v43_assertion_semantic_lineage"
branch_labels = None
depends_on = None


CREATE_TABLE_SQL = """
CREATE TABLE l2_pending_reviews (
    review_id TEXT PRIMARY KEY,
    decision_key TEXT NOT NULL UNIQUE,
    dedupe_key TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN ('goal_currentness','assertion_currentness','materialization','conflict')
    ),
    slot_key TEXT NOT NULL,
    value_fingerprint TEXT NOT NULL DEFAULT '',
    semantic_lineage_key TEXT NOT NULL DEFAULT '',
    claim_ids_json TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    proposed_json TEXT NOT NULL,
    route_contract_version INTEGER NOT NULL,
    evidence_rule_version INTEGER NOT NULL,
    source_generation INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','confirmed','rejected','closed')),
    version INTEGER NOT NULL DEFAULT 1,
    resolution_action TEXT,
    resolution_payload_json TEXT,
    resolution_event_id TEXT,
    resolved_by TEXT,
    close_reason TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    resolved_at REAL,
    CHECK (json_valid(claim_ids_json)),
    CHECK (json_valid(proposed_json)),
    CHECK (resolution_payload_json IS NULL OR json_valid(resolution_payload_json))
)
"""
CREATE_ACTIVE_DEDUPE_INDEX_SQL = """
CREATE UNIQUE INDEX idx_l2_pending_reviews_active_dedupe
    ON l2_pending_reviews(dedupe_key)
    WHERE status = 'pending'
"""
CREATE_SUBJECT_STATUS_INDEX_SQL = """
CREATE INDEX idx_l2_pending_reviews_subject_status
    ON l2_pending_reviews(subject_id, status, updated_at DESC)
"""
STATEMENTS = (
    CREATE_TABLE_SQL,
    CREATE_ACTIVE_DEDUPE_INDEX_SQL,
    CREATE_SUBJECT_STATUS_INDEX_SQL,
)
SCHEMA_SQL = ";\n".join(statement.strip() for statement in STATEMENTS) + ";"


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement.strip())


def schema_sql_for_fresh_database() -> str:
    """Return the fresh pending-review schema."""

    return SCHEMA_SQL


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS l2_pending_reviews")


__all__ = [
    "CREATE_ACTIVE_DEDUPE_INDEX_SQL",
    "CREATE_SUBJECT_STATUS_INDEX_SQL",
    "CREATE_TABLE_SQL",
    "SCHEMA_SQL",
    "STATEMENTS",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
