"""Durable external delivery intent owned by the chat transaction."""

OUTBOUND_DELIVERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_outbound_deliveries (
    delivery_id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES chat_messages(message_id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    endpoint_json TEXT NOT NULL,
    content_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','leased','sending','succeeded','uncertain','failed','expired','cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    retry_safe INTEGER NOT NULL DEFAULT 0,
    next_attempt_at_ms INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    lease_expires_at_ms INTEGER,
    expires_at_ms INTEGER NOT NULL,
    receipt_json TEXT,
    last_error TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_outbound_ready
    ON chat_outbound_deliveries(state,next_attempt_at_ms,created_at_ms);
CREATE INDEX IF NOT EXISTS idx_chat_outbound_message
    ON chat_outbound_deliveries(message_id);
CREATE TRIGGER IF NOT EXISTS trg_chat_outbound_hide
AFTER UPDATE OF is_visible, content_text ON chat_messages
WHEN NEW.is_visible=0 OR NEW.content_text IS NOT OLD.content_text
BEGIN
    UPDATE chat_outbound_deliveries SET
        state=CASE WHEN state='sending' THEN 'uncertain'
                   WHEN state IN ('pending','leased') THEN 'cancelled' ELSE state END,
        content_json='{}',lease_token=NULL,lease_expires_at_ms=NULL
        WHERE message_id=OLD.message_id;
END;
"""
