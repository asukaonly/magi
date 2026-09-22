"""Read-model revision and keyset index schema for isolated chat fixtures."""

READ_REVISION_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS chat_read_revisions (
        user_id TEXT NOT NULL,
        scope TEXT NOT NULL,
        epoch TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
        revision INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, scope)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_chat_sessions_page
       ON chat_sessions(user_id, updated_at_ms DESC, created_at_ms DESC, session_id DESC)
       WHERE deleted_at_ms IS NULL AND archived_at_ms IS NULL""",
    """CREATE INDEX IF NOT EXISTS idx_chat_messages_page
       ON chat_messages(user_id, session_id, created_at_ms DESC, sequence_no DESC, message_id DESC)
       WHERE is_visible = 1""",
    """CREATE INDEX IF NOT EXISTS idx_chat_messages_turn_page
       ON chat_messages(user_id, session_id, turn_id, created_at_ms DESC, sequence_no DESC, message_id DESC)
       WHERE is_visible = 1""",
    """CREATE INDEX IF NOT EXISTS idx_chat_turns_active_page
       ON chat_turns(user_id, session_id)
       WHERE status NOT IN ('completed', 'failed', 'cancelled', 'discarded', 'superseded')""",
]


def _bump(alias: str, scope: str) -> str:
    return f"""INSERT INTO chat_read_revisions(user_id, scope, revision)
        VALUES ({alias}.user_id, {scope}, 1)
        ON CONFLICT(user_id, scope) DO UPDATE SET revision = revision + 1;"""


for _table in ("chat_sessions", "chat_messages", "chat_turns", "chat_context_usage_snapshots"):
    for _operation, _aliases in (
        ("insert", ("NEW",)),
        ("update", ("OLD", "NEW")),
        ("delete", ("OLD",)),
    ):
        _actions = []
        for _alias in _aliases:
            _actions.append(_bump(_alias, f"{_alias}.session_id"))
            if _table == "chat_sessions":
                _actions.append(_bump(_alias, "''"))
        READ_REVISION_STATEMENTS.append(
            f"CREATE TRIGGER IF NOT EXISTS trg_{_table}_read_revision_{_operation} "
            f"AFTER {_operation.upper()} ON {_table} BEGIN {' '.join(_actions)} END"
        )
