"""Adopt the existing source journal without changing retained records."""
from alembic import op
revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_connections (
    connection_id TEXT PRIMARY KEY,
    plugin_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    disconnected INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS source_checkpoints (
    connection_id TEXT NOT NULL REFERENCES source_connections(connection_id),
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    cursor TEXT,
    revision INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (connection_id, source_id)
);
CREATE TABLE IF NOT EXISTS source_batches (
    batch_id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    checkpoint_revision INTEGER NOT NULL,
    body TEXT NOT NULL,
    UNIQUE (connection_id, source_id),
    FOREIGN KEY (connection_id, source_id)
        REFERENCES source_checkpoints(connection_id, source_id)
);
CREATE TABLE IF NOT EXISTS source_resources (
    resource_id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL REFERENCES source_connections(connection_id),
    reference_json TEXT NOT NULL,
    content BLOB NOT NULL,
    is_evidence INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS source_versions (
    connection_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    version TEXT NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN ('upsert', 'delete')),
    digest TEXT NOT NULL,
    evidence_id TEXT,
    receipt_json TEXT,
    accepted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(connection_id, source_id, object_id, version),
    FOREIGN KEY (connection_id, source_id)
        REFERENCES source_checkpoints(connection_id, source_id)
);
CREATE TABLE IF NOT EXISTS source_objects (
    connection_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    version TEXT NOT NULL,
    deleted INTEGER NOT NULL,
    PRIMARY KEY(connection_id, source_id, object_id),
    FOREIGN KEY (connection_id, source_id, object_id, version)
        REFERENCES source_versions(connection_id, source_id, object_id, version)
);
CREATE TABLE IF NOT EXISTS source_resource_owners (
    connection_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    version TEXT NOT NULL,
    resource_id TEXT NOT NULL REFERENCES source_resources(resource_id) ON DELETE CASCADE,
    PRIMARY KEY(connection_id, source_id, object_id, version, resource_id)
);
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)

def downgrade() -> None:
    raise RuntimeError("Source journal downgrade would destroy retained evidence")
