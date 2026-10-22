"""Retain explicit identity erasure separately from missing catalog evidence."""

from alembic import op

revision = "v57_entity_identity_tombstones"
down_revision = "v56_l0_outcome_receipts"
branch_labels = None
depends_on = None

STATEMENTS = (
    """CREATE TABLE entity_identity_tombstones (
        entity_id TEXT PRIMARY KEY,
        reason TEXT NOT NULL CHECK(reason IN ('forgotten', 'missing_redirect_target')),
        operation_id TEXT,
        created_at REAL NOT NULL
    )""",
    "CREATE INDEX idx_entity_source_bindings_entity ON entity_source_bindings(entity_id)",
    "CREATE INDEX idx_entity_identity_redirects_target ON entity_identity_redirects(target_entity_id)",
    "CREATE INDEX idx_entity_identity_operations_source ON entity_identity_operations(source_entity_id)",
    "CREATE INDEX idx_entity_identity_operations_target ON entity_identity_operations(target_entity_id)",
)
SCHEMA_SQL = ";\n".join(STATEMENTS) + ";"


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)
    op.execute("""
        INSERT OR IGNORE INTO entity_identity_tombstones(entity_id, reason, operation_id, created_at)
        SELECT json_extract(selector_json, '$.entity_id'), 'forgotten', operation_id, created_at
        FROM memory_forget_operations
        WHERE selector_kind = 'entity' AND execution_ready = 1
          AND COALESCE(json_extract(selector_json, '$.entity_id'), '') != ''
        ORDER BY created_at, operation_id
    """)
    op.execute("""
        INSERT OR IGNORE INTO entity_identity_tombstones(entity_id, reason, operation_id, created_at)
        SELECT redirects.target_entity_id, 'missing_redirect_target', redirects.operation_id,
               COALESCE(operations.created_at, 0)
        FROM entity_identity_redirects AS redirects
        LEFT JOIN entity_catalog AS catalog ON catalog.entity_id = redirects.target_entity_id
        LEFT JOIN entity_identity_operations AS operations ON operations.operation_id = redirects.operation_id
        WHERE catalog.entity_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM entity_identity_redirects AS next
              WHERE next.source_entity_id = redirects.target_entity_id
          )
        ORDER BY redirects.source_entity_id
    """)


def downgrade() -> None:
    for name in (
        "idx_entity_identity_operations_target",
        "idx_entity_identity_operations_source",
        "idx_entity_identity_redirects_target",
        "idx_entity_source_bindings_entity",
    ):
        op.execute(f"DROP INDEX {name}")
    op.execute("DROP TABLE entity_identity_tombstones")
