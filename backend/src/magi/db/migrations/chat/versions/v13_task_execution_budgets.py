"""Persist execution budgets across admissions and process restarts."""

from __future__ import annotations

from alembic import op

revision = "v13"
down_revision = "v12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_task_execution_budgets (
            root_turn_id TEXT NOT NULL PRIMARY KEY,
            max_llm_calls INTEGER NOT NULL CHECK (max_llm_calls > 0),
            llm_calls_used INTEGER NOT NULL DEFAULT 0
                CHECK (llm_calls_used >= 0 AND llm_calls_used <= max_llm_calls),
            max_worker_launches INTEGER NOT NULL CHECK (max_worker_launches > 0),
            worker_launches_used INTEGER NOT NULL DEFAULT 0
                CHECK (
                    worker_launches_used >= 0
                    AND worker_launches_used <= max_worker_launches
                ),
            created_at_ms INTEGER NOT NULL,
            FOREIGN KEY (root_turn_id)
                REFERENCES chat_turns(turn_id)
                ON DELETE CASCADE
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_task_execution_budgets")
