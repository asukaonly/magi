"""Add durable memory correction governance.

Revision ID: v4_memory_corrections
Revises: v3_experience_draft_cover
"""

from __future__ import annotations

import hashlib
import json
import time
import unicodedata
from typing import Any

from alembic import op

revision = "v4_memory_corrections"
down_revision = "v3_experience_draft_cover"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
ALTER TABLE tom_trait_assertions ADD COLUMN slot_key TEXT NOT NULL DEFAULT '';
ALTER TABLE tom_trait_assertions ADD COLUMN claim_fingerprint TEXT NOT NULL DEFAULT '';
ALTER TABLE tom_trait_assertions ADD COLUMN authority_ref TEXT;
ALTER TABLE tom_trait_assertions ADD COLUMN version_root_id TEXT;
ALTER TABLE tom_trait_assertions ADD COLUMN previous_version_id TEXT;
ALTER TABLE tom_trait_assertions ADD COLUMN valid_from REAL;
ALTER TABLE tom_trait_assertions ADD COLUMN valid_to REAL;
ALTER TABLE tom_trait_assertions ADD COLUMN scope_key TEXT NOT NULL DEFAULT 'global';
ALTER TABLE tom_trait_assertions ADD COLUMN scope_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE knowledge_graph ADD COLUMN slot_key TEXT NOT NULL DEFAULT '';
ALTER TABLE knowledge_graph ADD COLUMN claim_fingerprint TEXT NOT NULL DEFAULT '';
ALTER TABLE knowledge_graph ADD COLUMN authority_ref TEXT;
ALTER TABLE knowledge_graph ADD COLUMN scope_key TEXT NOT NULL DEFAULT 'global';
ALTER TABLE knowledge_graph ADD COLUMN scope_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE tom_snapshots ADD COLUMN source_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE user_profile_projection ADD COLUMN source_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE user_portrait_projection ADD COLUMN source_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE summaries ADD COLUMN source_revision INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS memory_corrections (
    correction_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    actor_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('assertion', 'edge')),
    target_id TEXT NOT NULL,
    slot_key TEXT NOT NULL,
    claim_fingerprint TEXT NOT NULL,
    correction_kind TEXT NOT NULL CHECK(
        correction_kind IN ('record_error', 'situation_changed', 'scope_refinement')
    ),
    reason TEXT,
    before_json TEXT NOT NULL,
    replacement_json TEXT,
    effective_at REAL,
    scope_json TEXT,
    source_event_id TEXT,
    audit_event_id TEXT,
    replacement_target_id TEXT,
    state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active', 'reverted')),
    created_at REAL NOT NULL,
    reverted_at REAL,
    reverted_by TEXT
);

CREATE TABLE IF NOT EXISTS memory_correction_rules (
    rule_id TEXT PRIMARY KEY,
    correction_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('assertion', 'edge')),
    rule_kind TEXT NOT NULL CHECK(
        rule_kind IN ('block_claim', 'authoritative_slot', 'close_before', 'scope_only')
    ),
    slot_key TEXT NOT NULL,
    claim_fingerprint TEXT,
    scope_key TEXT NOT NULL DEFAULT 'global',
    effective_from REAL,
    effective_to REAL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    FOREIGN KEY(correction_id) REFERENCES memory_corrections(correction_id)
);

CREATE TABLE IF NOT EXISTS memory_subject_revisions (
    subject_key TEXT PRIMARY KEY,
    revision INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_derivation_dependencies (
    artifact_kind TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('assertion', 'edge')),
    source_id TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    source_revision INTEGER NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(artifact_kind, artifact_id, source_kind, source_id)
);

CREATE TABLE IF NOT EXISTS memory_derivation_jobs (
    job_id TEXT PRIMARY KEY,
    correction_id TEXT NOT NULL,
    job_kind TEXT NOT NULL CHECK(
        job_kind IN ('l1_audit', 'snapshot', 'profile', 'portrait', 'l3_insight')
    ),
    target_key TEXT NOT NULL,
    target_revision INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(
        status IN ('pending', 'running', 'completed', 'failed')
    ),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at REAL,
    last_error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(correction_id) REFERENCES memory_corrections(correction_id),
    UNIQUE(correction_id, job_kind, target_key, target_revision)
);

CREATE TABLE IF NOT EXISTS knowledge_graph_versions (
    version_id TEXT PRIMARY KEY,
    triple_id TEXT NOT NULL,
    previous_version_id TEXT,
    slot_key TEXT NOT NULL,
    claim_fingerprint TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_id TEXT NOT NULL,
    object_type TEXT NOT NULL,
    fact_kind TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence_event_ids TEXT NOT NULL,
    evidence_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    valid_from REAL,
    valid_to REAL,
    scope_key TEXT NOT NULL DEFAULT 'global',
    scope_json TEXT NOT NULL DEFAULT '{}',
    authority_ref TEXT,
    correction_id TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_corrections_target_created
    ON memory_corrections(target_kind, target_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_corrections_slot_state
    ON memory_corrections(target_kind, slot_key, state, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_correction_rules_lookup
    ON memory_correction_rules(target_kind, slot_key, active, rule_kind);
CREATE INDEX IF NOT EXISTS idx_memory_derivation_dependencies_source
    ON memory_derivation_dependencies(source_kind, source_id);
CREATE INDEX IF NOT EXISTS idx_memory_derivation_dependencies_subject
    ON memory_derivation_dependencies(subject_key, source_revision);
CREATE INDEX IF NOT EXISTS idx_memory_derivation_jobs_ready
    ON memory_derivation_jobs(status, next_retry_at, created_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_graph_versions_triple_created
    ON knowledge_graph_versions(triple_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tom_assertions_slot_scope_status
    ON tom_trait_assertions(slot_key, scope_key, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_graph_slot_scope_status
    ON knowledge_graph(slot_key, scope_key, status, updated_at DESC);
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_knowledge_graph_slot_scope_status;
DROP INDEX IF EXISTS idx_tom_assertions_slot_scope_status;
DROP INDEX IF EXISTS idx_knowledge_graph_versions_triple_created;
DROP INDEX IF EXISTS idx_memory_derivation_jobs_ready;
DROP INDEX IF EXISTS idx_memory_derivation_dependencies_subject;
DROP INDEX IF EXISTS idx_memory_derivation_dependencies_source;
DROP INDEX IF EXISTS idx_memory_correction_rules_lookup;
DROP INDEX IF EXISTS idx_memory_corrections_slot_state;
DROP INDEX IF EXISTS idx_memory_corrections_target_created;
DROP TABLE IF EXISTS knowledge_graph_versions;
DROP TABLE IF EXISTS memory_derivation_jobs;
DROP TABLE IF EXISTS memory_derivation_dependencies;
DROP TABLE IF EXISTS memory_subject_revisions;
DROP TABLE IF EXISTS memory_correction_rules;
DROP TABLE IF EXISTS memory_corrections;
ALTER TABLE summaries DROP COLUMN source_revision;
ALTER TABLE user_portrait_projection DROP COLUMN source_revision;
ALTER TABLE user_profile_projection DROP COLUMN source_revision;
ALTER TABLE tom_snapshots DROP COLUMN source_revision;
ALTER TABLE knowledge_graph DROP COLUMN scope_json;
ALTER TABLE knowledge_graph DROP COLUMN scope_key;
ALTER TABLE knowledge_graph DROP COLUMN authority_ref;
ALTER TABLE knowledge_graph DROP COLUMN claim_fingerprint;
ALTER TABLE knowledge_graph DROP COLUMN slot_key;
ALTER TABLE tom_trait_assertions DROP COLUMN scope_json;
ALTER TABLE tom_trait_assertions DROP COLUMN scope_key;
ALTER TABLE tom_trait_assertions DROP COLUMN valid_to;
ALTER TABLE tom_trait_assertions DROP COLUMN valid_from;
ALTER TABLE tom_trait_assertions DROP COLUMN previous_version_id;
ALTER TABLE tom_trait_assertions DROP COLUMN version_root_id;
ALTER TABLE tom_trait_assertions DROP COLUMN authority_ref;
ALTER TABLE tom_trait_assertions DROP COLUMN claim_fingerprint;
ALTER TABLE tom_trait_assertions DROP COLUMN slot_key;
"""


def _normalized_text(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).strip().split()).casefold()


def _canonical_value(value: Any) -> str:
    if not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    text = value.strip()
    if text and text[0] in '[{"':
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        else:
            return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _normalized_text(text)


def _digest(*parts: Any) -> str:
    payload = "\x1f".join(_normalized_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _assertion_slot(row: dict[str, Any]) -> str:
    return f"assertion_slot_{_digest(row['entity_type'], row['entity_id'], row['trait_name'], row['target_entity_id'])}"


def _assertion_claim(row: dict[str, Any], slot_key: str) -> str:
    return f"assertion_claim_{_digest(slot_key, 'global', _canonical_value(row['trait_value']))}"


def _edge_slot(row: dict[str, Any]) -> str:
    return f"edge_slot_{_digest(row['subject_id'], row['predicate'], row['object_id'])}"


def _edge_claim(row: dict[str, Any], slot_key: str) -> str:
    return f"edge_claim_{_digest(slot_key, row['subject_id'], row['predicate'], row['object_id'], 'global')}"


def _row_dicts(connection: Any, query: str) -> list[dict[str, Any]]:
    cursor = connection.execute(query)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _root_assertion_id(
    assertion_id: str,
    previous_by_id: dict[str, str],
) -> str:
    current = assertion_id
    visited: set[str] = set()
    while current in previous_by_id and current not in visited:
        visited.add(current)
        current = previous_by_id[current]
    return current


def _backfill_assertions(connection: Any) -> None:
    rows = _row_dicts(
        connection,
        """
        SELECT assertion_id, entity_id, entity_type, trait_name, trait_value,
               target_entity_id, first_inferred_at, superseded_by
        FROM tom_trait_assertions
        """,
    )
    previous_by_id = {
        str(row["superseded_by"]): str(row["assertion_id"])
        for row in rows
        if row.get("superseded_by")
    }
    for row in rows:
        assertion_id = str(row["assertion_id"])
        slot_key = _assertion_slot(row)
        connection.execute(
            """
            UPDATE tom_trait_assertions
            SET slot_key = ?, claim_fingerprint = ?, version_root_id = ?,
                previous_version_id = ?, valid_from = COALESCE(valid_from, ?),
                scope_key = 'global', scope_json = '{}'
            WHERE assertion_id = ?
            """,
            (
                slot_key,
                _assertion_claim(row, slot_key),
                _root_assertion_id(assertion_id, previous_by_id),
                previous_by_id.get(assertion_id),
                float(row["first_inferred_at"]),
                assertion_id,
            ),
        )


def _backfill_edges(connection: Any) -> None:
    rows = _row_dicts(connection, "SELECT * FROM knowledge_graph")
    for row in rows:
        slot_key = _edge_slot(row)
        claim_fingerprint = _edge_claim(row, slot_key)
        triple_id = str(row["triple_id"])
        connection.execute(
            """
            UPDATE knowledge_graph
            SET slot_key = ?, claim_fingerprint = ?, scope_key = 'global', scope_json = '{}'
            WHERE triple_id = ?
            """,
            (slot_key, claim_fingerprint, triple_id),
        )
        version_id = f"kgv_{_digest(triple_id, row['created_at'])}"
        connection.execute(
            """
            INSERT OR IGNORE INTO knowledge_graph_versions(
                version_id, triple_id, previous_version_id, slot_key, claim_fingerprint,
                subject_id, subject_type, predicate, object_id, object_type, fact_kind,
                confidence, evidence_event_ids, evidence_text, status, valid_from, valid_to,
                scope_key, scope_json, authority_ref, correction_id, created_at
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'global', '{}', NULL, NULL, ?)
            """,
            (
                version_id,
                triple_id,
                slot_key,
                claim_fingerprint,
                str(row["subject_id"]),
                str(row["subject_type"]),
                str(row["predicate"]),
                str(row["object_id"]),
                str(row["object_type"]),
                str(row["fact_kind"]),
                float(row["confidence"]),
                str(row["evidence_event_ids"] or "[]"),
                str(row.get("evidence_text") or ""),
                str(row["status"]),
                row.get("valid_from"),
                row.get("valid_to"),
                float(row["created_at"]),
            ),
        )


def _ensure_subject_revisions(connection: Any) -> None:
    now = time.time()
    subjects = {
        str(row[0])
        for row in connection.execute(
            "SELECT entity_id FROM tom_trait_assertions UNION SELECT subject_id FROM knowledge_graph UNION SELECT object_id FROM knowledge_graph"
        ).fetchall()
        if row[0]
    }
    for subject_key in subjects:
        connection.execute(
            """
            INSERT OR IGNORE INTO memory_subject_revisions(subject_key, revision, updated_at)
            VALUES (?, 1, ?)
            """,
            (subject_key, now),
        )


def _migrate_rejected_rows(connection: Any) -> None:
    assertion_rows = _row_dicts(
        connection,
        "SELECT * FROM tom_trait_assertions WHERE status = 'user_rejected'",
    )
    edge_rows = _row_dicts(
        connection,
        "SELECT * FROM knowledge_graph WHERE status = 'user_rejected'",
    )
    for target_kind, rows, id_key in (
        ("assertion", assertion_rows, "assertion_id"),
        ("edge", edge_rows, "triple_id"),
    ):
        for row in rows:
            target_id = str(row[id_key])
            correction_id = f"correction_migrated_{_digest(target_kind, target_id)}"
            request_id = f"migration:{target_kind}:{target_id}"
            created_at = float(row.get("updated_at") or row.get("created_at") or 0.0)
            connection.execute(
                """
                INSERT OR IGNORE INTO memory_corrections(
                    correction_id, request_id, actor_id, target_kind, target_id,
                    slot_key, claim_fingerprint, correction_kind, reason, before_json,
                    replacement_json, effective_at, scope_json, source_event_id,
                    audit_event_id, replacement_target_id, state, created_at
                ) VALUES (?, ?, 'system:migration', ?, ?, ?, ?, 'record_error', NULL, ?,
                          NULL, ?, '{}', NULL, NULL, NULL, 'active', ?)
                """,
                (
                    correction_id,
                    request_id,
                    target_kind,
                    target_id,
                    str(row["slot_key"]),
                    str(row["claim_fingerprint"]),
                    json.dumps(row, ensure_ascii=False, sort_keys=True, default=str),
                    created_at,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO memory_correction_rules(
                    rule_id, correction_id, target_kind, rule_kind, slot_key,
                    claim_fingerprint, scope_key, active, created_at
                ) VALUES (?, ?, ?, 'block_claim', ?, ?, 'global', 1, ?)
                """,
                (
                    f"rule_{_digest(correction_id, 'block_claim')}",
                    correction_id,
                    target_kind,
                    str(row["slot_key"]),
                    str(row["claim_fingerprint"]),
                    created_at,
                ),
            )


def _backfill(connection: Any) -> None:
    _backfill_assertions(connection)
    _backfill_edges(connection)
    _ensure_subject_revisions(connection)
    _migrate_rejected_rows(connection)


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.executescript(SCHEMA_SQL)
    _backfill(connection)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
