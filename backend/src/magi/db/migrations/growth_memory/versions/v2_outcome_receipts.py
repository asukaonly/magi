"""Make persona growth effects atomic and independently replayable."""

from alembic import op

revision = "v2_outcome_receipts"
down_revision = "v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("relationships", recreate="always") as batch:
        batch.create_primary_key("pk_relationships_persona_user", ["persona_id", "user_id"])
    op.execute("""
        CREATE TABLE persona_outcome_receipts (
            persona_id TEXT NOT NULL, outcome_id TEXT NOT NULL,
            effect_kind TEXT NOT NULL, user_id TEXT NOT NULL, created_at REAL NOT NULL,
            PRIMARY KEY (persona_id, outcome_id, effect_kind)
        )
    """)


def downgrade() -> None:
    duplicate = op.get_bind().exec_driver_sql(
        "SELECT user_id FROM relationships GROUP BY user_id HAVING COUNT(*) > 1 LIMIT 1"
    ).first()
    if duplicate is not None:
        raise RuntimeError("Cannot downgrade relationships with multiple personas for one user")
    with op.batch_alter_table("relationships", recreate="always") as batch:
        batch.drop_constraint("pk_relationships_persona_user", type_="primary")
        batch.create_primary_key("pk_relationships_user", ["user_id"])
    op.execute("DROP TABLE persona_outcome_receipts")
