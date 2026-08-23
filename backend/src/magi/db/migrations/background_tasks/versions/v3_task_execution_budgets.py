"""Persist task-wide execution budgets for background retries."""

from __future__ import annotations

from alembic import op

revision = "v3"
down_revision = "v2"
branch_labels = None
depends_on = None

_COLUMNS: tuple[tuple[str, str], ...] = (
    ("task_max_llm_calls", "INTEGER"),
    ("task_llm_calls_used", "INTEGER NOT NULL DEFAULT 0"),
    ("task_max_worker_launches", "INTEGER"),
    ("task_worker_launches_used", "INTEGER NOT NULL DEFAULT 0"),
)


def upgrade() -> None:
    connection = op.get_bind().connection
    existing = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(background_tasks)").fetchall()
    }
    for name, ddl in _COLUMNS:
        if name not in existing:
            connection.execute(f"ALTER TABLE background_tasks ADD COLUMN {name} {ddl}")


def downgrade() -> None:
    connection = op.get_bind().connection
    used = connection.execute(
        """
        SELECT COUNT(*)
        FROM background_tasks
        WHERE task_llm_calls_used > 0 OR task_worker_launches_used > 0
        """
    ).fetchone()
    if used is not None and int(used[0]) > 0:
        raise RuntimeError(
            "Cannot downgrade background task budgets while execution capacity is used"
        )
    for name, _ in reversed(_COLUMNS):
        connection.execute(f"ALTER TABLE background_tasks DROP COLUMN {name}")
