"""Store traceable public reference dossiers with custom personas."""

from __future__ import annotations

from alembic import op

revision = "v3"
down_revision = "v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE TABLE IF NOT EXISTS persona_reference_dossiers (
        persona_id             TEXT PRIMARY KEY REFERENCES personas(persona_id),
        reference_fingerprint  TEXT NOT NULL,
        grounding_status       TEXT NOT NULL,
        dossier_json           TEXT NOT NULL,
        created_at             REAL NOT NULL,
        updated_at             REAL NOT NULL
        )"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS persona_reference_dossiers")
