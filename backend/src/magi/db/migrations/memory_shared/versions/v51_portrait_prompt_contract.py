"""Version cached portrait prompts independently of their UI representation."""

from __future__ import annotations

from alembic import op


revision = "v51_portrait_prompt_contract"
down_revision = "v50_profile_fact_descriptions"
branch_labels = None
depends_on = None

STATEMENTS = (
    "ALTER TABLE user_portrait_projection "
    "ADD COLUMN prompt_contract_version INTEGER NOT NULL DEFAULT 0",
    "DELETE FROM user_profile_projection",
)
SCHEMA_SQL = ";\n".join(STATEMENTS) + ";"


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE user_portrait_projection DROP COLUMN prompt_contract_version")
