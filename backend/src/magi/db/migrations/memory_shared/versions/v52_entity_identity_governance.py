"""Record identity reviews, source bindings and governed identity operations."""

from __future__ import annotations

from alembic import op
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

from sqlalchemy.engine import Connection

# revision identifiers, used by Alembic.
revision = "v52_entity_identity_governance"
down_revision = "v51_portrait_prompt_contract"
branch_labels = None
depends_on = None

STATEMENTS = (
    """CREATE TABLE entity_identity_reviews (
        review_id TEXT PRIMARY KEY,
        entity_id TEXT NOT NULL REFERENCES entity_catalog(entity_id) ON DELETE CASCADE,
        proposed_type TEXT NOT NULL,
        evidence_event_ids TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','applied','rejected')),
        version INTEGER NOT NULL DEFAULT 1,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        UNIQUE(entity_id, proposed_type)
    )""",
    """CREATE TABLE entity_identity_operations (
        operation_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL UNIQUE,
        request_fingerprint TEXT NOT NULL,
        operation_kind TEXT NOT NULL CHECK(operation_kind IN ('type_correction','merge')),
        source_entity_id TEXT NOT NULL,
        target_entity_id TEXT NOT NULL,
        previous_type TEXT NOT NULL,
        current_type TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        result_json TEXT NOT NULL,
        created_at REAL NOT NULL
    )""",
    """CREATE TABLE entity_identity_redirects (
        source_entity_id TEXT PRIMARY KEY,
        target_entity_id TEXT NOT NULL,
        operation_id TEXT NOT NULL,
        CHECK(source_entity_id != target_entity_id)
    )""",
    """CREATE TABLE entity_source_bindings (
        namespace TEXT NOT NULL,
        source_key_hash TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        PRIMARY KEY(namespace, source_key_hash)
    )""",
)
JOB_COLUMNS = "job_id, correction_id, job_kind, target_key, target_revision, status, attempt_count, next_retry_at, last_error, created_at, updated_at"
JOB_STATEMENTS = (
    """CREATE TABLE memory_derivation_jobs_new (
        job_id TEXT PRIMARY KEY,
        correction_id TEXT REFERENCES memory_corrections(correction_id),
        entity_operation_id TEXT REFERENCES entity_identity_operations(operation_id),
        job_kind TEXT NOT NULL CHECK(job_kind IN ('l1_audit','snapshot','profile','portrait','l3_insight')),
        target_key TEXT NOT NULL,
        target_revision INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','completed','failed')),
        attempt_count INTEGER NOT NULL DEFAULT 0,
        next_retry_at REAL,
        last_error TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        CHECK((correction_id IS NOT NULL) != (entity_operation_id IS NOT NULL)),
        CHECK(entity_operation_id IS NULL OR job_kind != 'l1_audit'),
        UNIQUE(correction_id, job_kind, target_key, target_revision),
        UNIQUE(entity_operation_id, job_kind, target_key, target_revision)
    )""",
    f"INSERT INTO memory_derivation_jobs_new({JOB_COLUMNS}) SELECT {JOB_COLUMNS} FROM memory_derivation_jobs",
    "DROP TABLE memory_derivation_jobs",
    "ALTER TABLE memory_derivation_jobs_new RENAME TO memory_derivation_jobs",
    "CREATE INDEX idx_memory_derivation_jobs_ready ON memory_derivation_jobs(status, next_retry_at, created_at)",
)
SCHEMA_SQL = ";\n".join((*STATEMENTS, *JOB_STATEMENTS)) + ";"


def upgrade() -> None:
    for statement in (*STATEMENTS, *JOB_STATEMENTS):
        op.execute(statement)
    connection = op.get_bind()
    database = connection.exec_driver_sql("PRAGMA database_list").fetchone()[2]
    if database:
        _backfill_source_bindings(connection, Path(database).with_name("l1_events.db"))


def downgrade() -> None:
    op.execute("DELETE FROM memory_derivation_jobs WHERE entity_operation_id IS NOT NULL")
    op.execute("ALTER TABLE memory_derivation_jobs RENAME TO memory_derivation_jobs_new")
    op.execute("DROP INDEX idx_memory_derivation_jobs_ready")
    op.execute("""CREATE TABLE memory_derivation_jobs (
        job_id TEXT PRIMARY KEY,
        correction_id TEXT NOT NULL REFERENCES memory_corrections(correction_id),
        job_kind TEXT NOT NULL CHECK(job_kind IN ('l1_audit','snapshot','profile','portrait','l3_insight')),
        target_key TEXT NOT NULL, target_revision INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','completed','failed')),
        attempt_count INTEGER NOT NULL DEFAULT 0, next_retry_at REAL, last_error TEXT,
        created_at REAL NOT NULL, updated_at REAL NOT NULL,
        UNIQUE(correction_id, job_kind, target_key, target_revision)
    )""")
    op.execute(
        f"INSERT INTO memory_derivation_jobs({JOB_COLUMNS}) SELECT {JOB_COLUMNS} FROM memory_derivation_jobs_new"
    )
    op.execute("DROP TABLE memory_derivation_jobs_new")
    op.execute(
        "CREATE INDEX idx_memory_derivation_jobs_ready ON memory_derivation_jobs(status, next_retry_at, created_at)"
    )
    for table in (
        "entity_source_bindings",
        "entity_identity_redirects",
        "entity_identity_operations",
        "entity_identity_reviews",
    ):
        op.execute(f"DROP TABLE {table}")


def _backfill_source_bindings(connection: Connection, l1_path: Path) -> None:
    """Recover pre-registry source identities from exact source keys during upgrade only.

    Source keys prove producer identity. Display labels never authorize a merge.
    Older duplicate rows remain available for explicit identity review.
    """
    if not l1_path.is_file():
        return
    with sqlite3.connect(l1_path.as_uri() + "?mode=ro", uri=True) as l1:
        for event_id, source, metadata in l1.execute(
            "SELECT event_id, source, metadata_json FROM fact_events "
            "WHERE deleted_at IS NULL AND metadata_json IS NOT NULL ORDER BY timestamp, id"
        ):
            if connection.exec_driver_sql(
                "SELECT 1 FROM memory_source_event_tombstones WHERE event_id = ?", (event_id,)
            ).fetchone():
                continue
            try:
                payload = json.loads(metadata)
            except (TypeError, ValueError):
                continue
            hints = payload.get("structured_entity_hints") if isinstance(payload, dict) else None
            if not isinstance(hints, list):
                continue
            for hint in hints:
                if not isinstance(hint, dict):
                    continue
                key = str(hint.get("source_entity_key") or "").strip()
                kind = str(hint.get("entity_type") or "").strip().casefold()
                if not key or not kind:
                    continue
                # Frozen pre-v52 source identity serialization, used only for data migration.
                encoded = json.dumps([kind, source, key], ensure_ascii=False)
                entity_id = f"{kind}:source:{uuid.uuid5(uuid.NAMESPACE_URL, encoded).hex}"
                resolved = str(hint.get("resolved_entity_id") or entity_id)
                exists = connection.exec_driver_sql(
                    "SELECT entity_id FROM entity_catalog WHERE entity_id = ?",
                    (resolved,),
                ).fetchone()
                if not exists:
                    continue
                connection.exec_driver_sql(
                    "INSERT OR IGNORE INTO entity_source_bindings(namespace, source_key_hash, entity_id) VALUES (?, ?, ?)",
                    (source, hashlib.sha256(key.encode()).hexdigest(), resolved),
                )
