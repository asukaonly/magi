"""knowledge_graph.evidence_class — provenance class for retrieval policy

Revision ID: 0010_kg_evidence_class
Revises: 0009_manual_entries_body_doc
Create Date: 2026-05-21

Phase 1 of evidence-aware retrieval. Each KG edge gets a coarse provenance
label (USER_SELF_REPORT / EXTERNAL_OBSERVATION / AGENT_INFERENCE / ...) that
the L2 recall stack uses as both a hard filter and a rerank prior.

NULL is intentional and load-bearing: it means "unknown — apply default
policy weight at rerank time, do NOT exclude on filter". Existing rows stay
NULL until the Task 5 backfill heuristic labels them; everything downstream
(filter in Task 6, reranker in Task 10) is wired to treat NULL as neutral
rather than as a third value that breaks recall.

The partial index — restricted to non-NULL rows — is what makes the
filter cheap: in practice most read paths ask for a specific class set, and
the planner can skip the (still very common) unknown rows entirely.
"""

from __future__ import annotations

from alembic import op

revision = "0010_kg_evidence_class"
down_revision = "0009_manual_entries_body_doc"
branch_labels = None
depends_on = None


# Named SCHEMA_SQL so the test schema helper (tests/_shared/memory_schema.py)
# picks it up via regex alongside the other migrations on a fresh DB.
SCHEMA_SQL = """
ALTER TABLE knowledge_graph ADD COLUMN evidence_class TEXT DEFAULT NULL;
CREATE INDEX IF NOT EXISTS idx_knowledge_graph_evidence_class
    ON knowledge_graph(evidence_class)
    WHERE evidence_class IS NOT NULL;
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_knowledge_graph_evidence_class;
ALTER TABLE knowledge_graph DROP COLUMN evidence_class;
"""


def upgrade() -> None:
    """Add evidence_class column + partial index — defensively.

    Mirrors 0008/0009: the column may already exist if a dev hand-applied
    the ALTER while the migration was in flight (the regression-test fixture
    landing in Task 1 already references EvidenceClass on writes, so the
    drift window is real). SQLite has no ``ADD COLUMN IF NOT EXISTS``, so
    introspect PRAGMA table_info first and skip the ALTER when the column
    is already present. The index creation is already idempotent via
    ``CREATE INDEX IF NOT EXISTS`` so it runs unconditionally.
    """
    conn = op.get_bind().connection
    cursor = conn.execute("PRAGMA table_info(knowledge_graph)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    if "evidence_class" in existing_columns:
        # Column already present; still ensure the index exists.
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_knowledge_graph_evidence_class
                ON knowledge_graph(evidence_class)
                WHERE evidence_class IS NOT NULL;
            """
        )
    else:
        conn.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
