"""Store evidence-backed thoughts without changing relationship statistics."""

from alembic import op

revision = "v3_persona_reflections"
down_revision = "v2_outcome_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE persona_reflections (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, persona_id TEXT NOT NULL,
        topic TEXT NOT NULL, content_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
        persona_revision REAL NOT NULL, governance_revision TEXT NOT NULL,
        created_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'active',
        shared_at REAL,
        CHECK (status IN ('active', 'dismissed', 'stale'))
    )""")
    op.execute("CREATE INDEX idx_reflections_owner ON persona_reflections(user_id, persona_id, created_at DESC)")
    op.execute("""CREATE TABLE persona_reflection_runs (
        run_key TEXT PRIMARY KEY, user_id TEXT NOT NULL, persona_id TEXT NOT NULL,
        created_at REAL NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 1,
        CHECK (status IN ('running', 'completed', 'failed', 'stale'))
    )""")
    op.execute("CREATE INDEX idx_reflection_runs_owner ON persona_reflection_runs(user_id, persona_id, created_at DESC)")


def downgrade() -> None:
    op.drop_table("persona_reflection_runs")
    op.drop_table("persona_reflections")
