"""Keep source browse cursors stable across secure content compaction."""
from alembic import op

revision = "v3"
down_revision = "v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().connection.executescript("""
ALTER TABLE source_versions ADD COLUMN read_order INTEGER NOT NULL DEFAULT 0;
UPDATE source_versions SET read_order=rowid;
CREATE UNIQUE INDEX idx_source_version_read_order ON source_versions(read_order);
CREATE INDEX idx_source_scoped_read_order ON source_versions(connection_id, source_id, read_order DESC);
CREATE TABLE source_read_sequence (id INTEGER PRIMARY KEY CHECK(id=1), value INTEGER NOT NULL);
INSERT INTO source_read_sequence SELECT 1, COALESCE(MAX(read_order),0) FROM source_versions;
""")


def downgrade() -> None:
    op.execute("DROP TABLE source_read_sequence")
    op.execute("DROP INDEX idx_source_scoped_read_order")
    op.execute("DROP INDEX idx_source_version_read_order")
    op.execute("ALTER TABLE source_versions DROP COLUMN read_order")
