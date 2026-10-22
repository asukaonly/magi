"""Channel bindings, receipts and outreach share one MySQL transaction owner."""

from alembic import op

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

_TABLES = (
    """CREATE TABLE IF NOT EXISTS channel_session_mappings (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        identity_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
        session_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        channel_type LONGTEXT NOT NULL, external_chat_id LONGTEXT NOT NULL,
        external_thread_id LONGTEXT NOT NULL, magi_session_id LONGTEXT NOT NULL,
        magi_user_id LONGTEXT NOT NULL, is_group BOOLEAN NOT NULL,
        created_at_ms BIGINT NOT NULL, last_active_at_ms BIGINT NOT NULL,
        metadata_json LONGTEXT NOT NULL,
        INDEX idx_csm_session(session_key)
    )""",
    """CREATE TABLE IF NOT EXISTS channel_notification_cursors (
        identity_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        channel_type LONGTEXT NOT NULL, external_chat_id LONGTEXT NOT NULL,
        last_notification_id BIGINT NOT NULL, updated_at_ms BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS channel_relay_state (
        identity_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        state_key LONGTEXT NOT NULL, value_integer BIGINT NOT NULL, updated_at_ms BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS channel_binding_settings (
        identity_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        channel_type LONGTEXT NOT NULL, external_user_id LONGTEXT NOT NULL,
        auto_approve BOOLEAN NOT NULL, updated_at_ms BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS delivery_receipts (
        receipt_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        session_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        run_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        session_id LONGTEXT NOT NULL, run_id LONGTEXT NOT NULL, revision BIGINT NOT NULL,
        channel_id LONGTEXT NOT NULL, external_message_id LONGTEXT,
        magi_session_id LONGTEXT NOT NULL, delivered_at_ms BIGINT NOT NULL,
        created_at_ms BIGINT NOT NULL, INDEX idx_dr_run(session_key,run_key,revision)
    )""",
    """CREATE TABLE IF NOT EXISTS outreach_outbox (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        identity_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
        creation_token CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        correlation_id LONGTEXT NOT NULL, channel_scope LONGTEXT NOT NULL,
        intent_fingerprint LONGTEXT NOT NULL, intent_json LONGTEXT NOT NULL,
        release_at_ms BIGINT NOT NULL, status VARCHAR(32) NOT NULL,
        created_at_ms BIGINT NOT NULL, INDEX ix_outreach_outbox_due(status,release_at_ms)
    )""",
    """CREATE TABLE IF NOT EXISTS outreach_delivery_log (
        identity_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        user_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        correlation_id LONGTEXT NOT NULL, user_id LONGTEXT NOT NULL,
        channel_type LONGTEXT NOT NULL, delivered_at_ms BIGINT NOT NULL,
        INDEX ix_outreach_delivery_log_user(user_key,delivered_at_ms)
    )""",
)


def upgrade() -> None:
    for statement in _TABLES:
        op.execute(statement + " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin")


def downgrade() -> None:
    raise RuntimeError("Export channel state before changing its storage schema")
