"""Persist complete governed relationship version metadata.

Revision ID: v10_relationship_version_snapshot
Revises: v9_memory_clear_generation
"""

from __future__ import annotations

from alembic import op

revision = "v10_relationship_version_snapshot"
down_revision = "v9_memory_clear_generation"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
ALTER TABLE knowledge_graph_versions ADD COLUMN natural_summary TEXT;
ALTER TABLE knowledge_graph_versions ADD COLUMN observation_count INTEGER;
ALTER TABLE knowledge_graph_versions ADD COLUMN first_observed_at REAL;
ALTER TABLE knowledge_graph_versions ADD COLUMN last_observed_at REAL;
ALTER TABLE knowledge_graph_versions ADD COLUMN last_confirmed_at REAL;
ALTER TABLE knowledge_graph_versions ADD COLUMN source_type TEXT;
ALTER TABLE knowledge_graph_versions ADD COLUMN extraction_method TEXT;
ALTER TABLE knowledge_graph_versions ADD COLUMN expires_at REAL;
ALTER TABLE knowledge_graph_versions ADD COLUMN evidence_class TEXT;
ALTER TABLE knowledge_graph_versions ADD COLUMN edge_created_at REAL;
ALTER TABLE knowledge_graph_versions
    ADD COLUMN governance_complete INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_kg_versions_governed_subject_time
    ON knowledge_graph_versions(
        governance_complete, subject_id, predicate, scope_key, valid_from, created_at DESC
    );
CREATE INDEX IF NOT EXISTS idx_kg_versions_governed_object_time
    ON knowledge_graph_versions(
        governance_complete, object_id, predicate, scope_key, valid_from, created_at DESC
    );
CREATE INDEX IF NOT EXISTS idx_kg_versions_governed_predicate_time
    ON knowledge_graph_versions(
        governance_complete, predicate, scope_key, valid_from, created_at DESC
    );
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_kg_versions_governed_predicate_time")
    op.execute("DROP INDEX IF EXISTS idx_kg_versions_governed_object_time")
    op.execute("DROP INDEX IF EXISTS idx_kg_versions_governed_subject_time")
    op.execute("ALTER TABLE knowledge_graph_versions DROP COLUMN governance_complete")
    op.execute("ALTER TABLE knowledge_graph_versions DROP COLUMN edge_created_at")
    op.execute("ALTER TABLE knowledge_graph_versions DROP COLUMN evidence_class")
    op.execute("ALTER TABLE knowledge_graph_versions DROP COLUMN expires_at")
    op.execute("ALTER TABLE knowledge_graph_versions DROP COLUMN extraction_method")
    op.execute("ALTER TABLE knowledge_graph_versions DROP COLUMN source_type")
    op.execute("ALTER TABLE knowledge_graph_versions DROP COLUMN last_confirmed_at")
    op.execute("ALTER TABLE knowledge_graph_versions DROP COLUMN last_observed_at")
    op.execute("ALTER TABLE knowledge_graph_versions DROP COLUMN first_observed_at")
    op.execute("ALTER TABLE knowledge_graph_versions DROP COLUMN observation_count")
    op.execute("ALTER TABLE knowledge_graph_versions DROP COLUMN natural_summary")


__all__ = ["SCHEMA_SQL", "downgrade", "upgrade"]
