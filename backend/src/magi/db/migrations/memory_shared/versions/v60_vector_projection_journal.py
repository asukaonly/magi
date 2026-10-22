"""Keep desired remote vector revisions and replayable projection operations."""

from alembic import op

revision = "v60_vector_projection_journal"
down_revision = "v59_timeline_cover_preferences"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE vector_projection_namespaces (
    namespace TEXT PRIMARY KEY,
    backend_identity TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE vector_projection_collections (
    namespace TEXT NOT NULL REFERENCES vector_projection_namespaces(namespace),
    collection_id TEXT PRIMARY KEY,
    generation INTEGER NOT NULL
);
CREATE TABLE vector_projection_entries (
    namespace TEXT NOT NULL REFERENCES vector_projection_namespaces(namespace),
    entity_id TEXT NOT NULL,
    model_key TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    record_id TEXT NOT NULL UNIQUE,
    collection_id TEXT NOT NULL,
    partition_value TEXT,
    published INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(namespace,entity_id,model_key)
);
CREATE TABLE vector_projection_operations (
    operation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL REFERENCES vector_projection_namespaces(namespace),
    kind TEXT NOT NULL CHECK(kind IN ('upsert','delete','clear')),
    collection_id TEXT NOT NULL,
    record_id TEXT,
    payload_json TEXT
);
CREATE INDEX idx_vector_projection_pending ON vector_projection_operations(namespace,operation_id);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    for table in (
        "vector_projection_operations",
        "vector_projection_entries",
        "vector_projection_collections",
        "vector_projection_namespaces",
    ):
        op.execute(f"DROP TABLE {table}")
