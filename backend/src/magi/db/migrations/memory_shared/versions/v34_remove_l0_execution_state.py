"""Remove chat execution state from optional L0 working memory."""

from __future__ import annotations

from alembic import op

revision = "v34_remove_l0_execution_state"
down_revision = "v33_chat_forget_activation"
branch_labels = None
depends_on = None

DROP_STATEMENTS = (
    "DROP TABLE IF EXISTS l0_execution_pending_turns",
    "DROP TABLE IF EXISTS l0_execution_results",
    "DROP TABLE IF EXISTS l0_execution_runs",
)
DROP_SQL = ";\n".join(DROP_STATEMENTS) + ";"


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a fresh shared-memory database."""

    return ""


def upgrade() -> None:
    for statement in DROP_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("L0 execution checkpoints cannot be restored")
