"""Persist accepted post-turn intents and frozen analysis batches."""

from alembic import op

revision = "v19_post_turn_outbox"
down_revision = "v18"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chat_post_turn_batches (
    batch_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    state TEXT NOT NULL CHECK(state IN ('pending', 'claimed', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at_ms INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    lease_expires_at_ms INTEGER,
    analysis_json TEXT,
    settled_json TEXT NOT NULL DEFAULT '[]',
    last_error TEXT,
    updated_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_post_turn_batches_ready
    ON chat_post_turn_batches(state, next_attempt_at_ms, lease_expires_at_ms);
CREATE TABLE IF NOT EXISTS chat_post_turn_outcomes (
    outcome_id TEXT PRIMARY KEY,
    source_turn_id TEXT NOT NULL REFERENCES chat_turns(turn_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    persona_id TEXT,
    source_message_ids TEXT NOT NULL,
    accepted_at_ms INTEGER NOT NULL,
    execution_mode TEXT,
    delivery_attempt_no INTEGER,
    task_id TEXT,
    task_attempt INTEGER,
    batch_id TEXT REFERENCES chat_post_turn_batches(batch_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_post_turn_outcomes_ready
    ON chat_post_turn_outcomes(batch_id, accepted_at_ms, outcome_id);
CREATE INDEX IF NOT EXISTS idx_chat_post_turn_outcomes_source
    ON chat_post_turn_outcomes(session_id, source_turn_id);
CREATE TRIGGER IF NOT EXISTS trg_chat_post_turn_reject_unavailable_session
BEFORE INSERT ON chat_post_turn_outcomes
WHEN EXISTS (SELECT 1 FROM chat_global_clear_intent)
 OR EXISTS (SELECT 1 FROM chat_cleared_session_scopes WHERE session_id=NEW.session_id COLLATE NOCASE)
 OR NOT EXISTS (SELECT 1 FROM chat_sessions WHERE session_id=NEW.session_id
                AND deleted_at_ms IS NULL AND archived_at_ms IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'chat session is unavailable');
END;
CREATE TRIGGER IF NOT EXISTS trg_chat_post_turn_revoke_batch
AFTER DELETE ON chat_post_turn_outcomes
WHEN OLD.batch_id IS NOT NULL
BEGIN
    DELETE FROM chat_post_turn_batches WHERE batch_id=OLD.batch_id;
END;
CREATE TRIGGER IF NOT EXISTS trg_chat_post_turn_delete_message
AFTER DELETE ON chat_messages
BEGIN
    DELETE FROM chat_post_turn_outcomes WHERE session_id=OLD.session_id AND (
        source_turn_id=OLD.turn_id AND OLD.role='user'
        OR EXISTS (SELECT 1 FROM json_each(source_message_ids) WHERE value=OLD.message_id)
    );
END;
CREATE TRIGGER IF NOT EXISTS trg_chat_post_turn_hide_message
AFTER UPDATE OF is_visible, content_text ON chat_messages
WHEN NEW.is_visible=0 OR NEW.content_text IS NOT OLD.content_text
BEGIN
    DELETE FROM chat_post_turn_outcomes WHERE session_id=OLD.session_id AND (
        source_turn_id=OLD.turn_id AND OLD.role='user'
        OR EXISTS (SELECT 1 FROM json_each(source_message_ids) WHERE value=OLD.message_id)
    );
END;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    for name in ("hide_message", "delete_message", "revoke_batch", "reject_unavailable_session"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_chat_post_turn_{name}")
    op.execute("DROP TABLE chat_post_turn_outcomes")
    op.execute("DROP TABLE chat_post_turn_batches")
