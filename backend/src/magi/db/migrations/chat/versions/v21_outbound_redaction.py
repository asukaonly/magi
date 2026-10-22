"""Retain delivery evidence after message redaction."""
from alembic import op

revision = "v21_outbound_redaction"
down_revision = "v20_outbound_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_chat_outbound_hide")
    op.get_bind().connection.executescript("""
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
""")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_chat_outbound_hide")
    op.get_bind().connection.executescript("""
CREATE TRIGGER trg_chat_outbound_hide
AFTER UPDATE OF is_visible, content_text ON chat_messages
WHEN NEW.is_visible=0 OR NEW.content_text IS NOT OLD.content_text
BEGIN
    DELETE FROM chat_outbound_deliveries WHERE message_id=OLD.message_id;
END;
""")
