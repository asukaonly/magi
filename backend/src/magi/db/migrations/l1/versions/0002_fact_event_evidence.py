"""add event-level evidence annotations

Revision ID: 0002_fact_event_evidence
Revises: 0001_initial
Create Date: 2026-05-09

Adds durable event-level evidence classification and policy columns to
``fact_events``. Raw L1 content remains immutable; these columns describe
retrieval and L2-write authority for the event.
"""

from __future__ import annotations

from alembic import op


revision = "0002_fact_event_evidence"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


UPGRADE_SQL = """
ALTER TABLE fact_events ADD COLUMN evidence_status TEXT NOT NULL DEFAULT 'unclassified';
ALTER TABLE fact_events ADD COLUMN evidence_class TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE fact_events ADD COLUMN evidence_reason_code TEXT NOT NULL DEFAULT 'unclassified';
ALTER TABLE fact_events ADD COLUMN evidence_speaker_role TEXT;
ALTER TABLE fact_events ADD COLUMN evidence_grounding_type TEXT;
ALTER TABLE fact_events ADD COLUMN evidence_semantic_owner TEXT;
ALTER TABLE fact_events ADD COLUMN evidence_originality_type TEXT;
ALTER TABLE fact_events ADD COLUMN evidence_source_event_ids_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE fact_events ADD COLUMN evidence_confidence REAL NOT NULL DEFAULT 0.0;
ALTER TABLE fact_events ADD COLUMN evidence_classifier_version TEXT NOT NULL DEFAULT 'unclassified';
ALTER TABLE fact_events ADD COLUMN evidence_policy_version TEXT NOT NULL DEFAULT 'unclassified';
ALTER TABLE fact_events ADD COLUMN l1_retrieval_scope TEXT NOT NULL DEFAULT 'none';
ALTER TABLE fact_events ADD COLUMN l2_graph_scope TEXT NOT NULL DEFAULT 'none';
ALTER TABLE fact_events ADD COLUMN l2_assertion_scope TEXT NOT NULL DEFAULT 'none';
ALTER TABLE fact_events ADD COLUMN evidence_skip_reason TEXT;
ALTER TABLE fact_events ADD COLUMN evidence_updated_at REAL;

CREATE INDEX IF NOT EXISTS idx_fact_events_evidence_status
    ON fact_events(evidence_status);
CREATE INDEX IF NOT EXISTS idx_fact_events_evidence_class
    ON fact_events(evidence_class);
CREATE INDEX IF NOT EXISTS idx_fact_events_l1_retrieval_scope
    ON fact_events(l1_retrieval_scope, user_id, timestamp DESC);
"""

DOWNGRADE_SQL = """
DROP INDEX IF EXISTS idx_fact_events_l1_retrieval_scope;
DROP INDEX IF EXISTS idx_fact_events_evidence_class;
DROP INDEX IF EXISTS idx_fact_events_evidence_status;
ALTER TABLE fact_events DROP COLUMN evidence_updated_at;
ALTER TABLE fact_events DROP COLUMN evidence_skip_reason;
ALTER TABLE fact_events DROP COLUMN l2_assertion_scope;
ALTER TABLE fact_events DROP COLUMN l2_graph_scope;
ALTER TABLE fact_events DROP COLUMN l1_retrieval_scope;
ALTER TABLE fact_events DROP COLUMN evidence_policy_version;
ALTER TABLE fact_events DROP COLUMN evidence_classifier_version;
ALTER TABLE fact_events DROP COLUMN evidence_confidence;
ALTER TABLE fact_events DROP COLUMN evidence_source_event_ids_json;
ALTER TABLE fact_events DROP COLUMN evidence_originality_type;
ALTER TABLE fact_events DROP COLUMN evidence_semantic_owner;
ALTER TABLE fact_events DROP COLUMN evidence_grounding_type;
ALTER TABLE fact_events DROP COLUMN evidence_speaker_role;
ALTER TABLE fact_events DROP COLUMN evidence_reason_code;
ALTER TABLE fact_events DROP COLUMN evidence_class;
ALTER TABLE fact_events DROP COLUMN evidence_status;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(UPGRADE_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DOWNGRADE_SQL)