"""Track every persisted trace decoration change by chat owner."""

from alembic import op

revision = "v9"
down_revision = "v8"
branch_labels = None
depends_on = None

_DIRECT_TABLES = ("trace_turns", "agent_run_manifests")
_TRACE_TABLES = ("trace_spans", "trace_llm_calls", "trace_tools")
_RUN_TABLES = ("agent_run_events", "run_plans")
_TABLES = (*_DIRECT_TABLES, *_TRACE_TABLES, *_RUN_TABLES)


def _bump(table: str, alias: str) -> str:
    if table in _DIRECT_TABLES:
        owner = f"SELECT {alias}.user_id, {alias}.session_id, 1 WHERE {alias}.user_id IS NOT NULL AND {alias}.session_id IS NOT NULL"
    elif table in _TRACE_TABLES:
        owner = f"SELECT user_id, session_id, 1 FROM trace_turns WHERE trace_id = {alias}.trace_id"
    else:
        owner = f"SELECT user_id, session_id, 1 FROM agent_run_manifests WHERE run_id = {alias}.run_id AND user_id IS NOT NULL AND session_id IS NOT NULL"
    return f"""INSERT INTO trace_read_revisions(user_id, session_id, revision)
        {owner}
        ON CONFLICT(user_id, session_id) DO UPDATE SET revision = revision + 1;"""


def upgrade() -> None:
    op.execute("""CREATE TABLE trace_read_revisions (
        user_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        epoch TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
        revision INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, session_id)
    )""")
    for table in _TABLES:
        for operation, aliases in (
            ("insert", ("NEW",)),
            ("update", ("OLD", "NEW")),
            ("delete", ("OLD",)),
        ):
            actions = " ".join(_bump(table, alias) for alias in aliases)
            op.execute(f"""CREATE TRIGGER trg_{table}_read_revision_{operation}
                AFTER {operation.upper()} ON {table} BEGIN {actions} END""")
    op.execute("""INSERT OR IGNORE INTO trace_read_revisions(user_id, session_id)
        SELECT user_id, session_id FROM trace_turns
        UNION SELECT user_id, session_id FROM agent_run_manifests
        WHERE user_id IS NOT NULL AND session_id IS NOT NULL""")


def downgrade() -> None:
    for table in _TABLES:
        for operation in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER trg_{table}_read_revision_{operation}")
    op.execute("DROP TABLE trace_read_revisions")
