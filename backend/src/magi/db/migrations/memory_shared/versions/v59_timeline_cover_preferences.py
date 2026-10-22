"""Own the previously runtime-created timeline preference schema."""

from alembic import op

revision = "v59_timeline_cover_preferences"
down_revision = "v58_history_import_source_roles"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS timeline_cover_preferences (
    scope_key TEXT PRIMARY KEY,
    scale TEXT NOT NULL,
    period_start REAL NOT NULL,
    period_end REAL NOT NULL,
    mode TEXT NOT NULL,
    asset_ref TEXT,
    source TEXT NOT NULL DEFAULT 'current_period',
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_timeline_cover_preferences_period
    ON timeline_cover_preferences(scale,period_start,period_end);
CREATE INDEX IF NOT EXISTS idx_timeline_cover_preferences_asset
    ON timeline_cover_preferences(asset_ref) WHERE mode='asset';
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    # Existing user preferences predate this migration; preserve their contents.
    op.execute("DROP INDEX IF EXISTS idx_timeline_cover_preferences_asset")
