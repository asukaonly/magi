"""Persist claim and evidence barriers created by user forgetting.

Revision ID: v18_persistent_forget_governance
Revises: v17_scheduled_correction_cancellation
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import unicodedata
import uuid
from typing import Any

from alembic import op

revision = "v18_persistent_forget_governance"
down_revision = "v17_scheduled_correction_cancellation"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_forget_claim_rules (
    rule_id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('assertion', 'edge')),
    claim_fingerprint TEXT NOT NULL,
    semantic_fingerprint TEXT NOT NULL,
    forget_kind TEXT NOT NULL CHECK(forget_kind IN ('entity', 'time_range')),
    effective_from REAL,
    effective_to REAL,
    evidence_fail_closed INTEGER NOT NULL DEFAULT 0 CHECK(
        evidence_fail_closed IN (0, 1)
    ),
    created_at REAL NOT NULL,
    CHECK(
        (forget_kind = 'entity' AND effective_from IS NULL AND effective_to IS NULL)
        OR (
            forget_kind = 'time_range'
            AND effective_from IS NOT NULL
            AND effective_to IS NOT NULL
            AND effective_to >= effective_from
        )
    )
);
CREATE INDEX IF NOT EXISTS idx_memory_forget_claim_rules_lookup
    ON memory_forget_claim_rules(
        target_kind, semantic_fingerprint, forget_kind,
        effective_from, effective_to
    );

CREATE TABLE IF NOT EXISTS memory_forget_evidence_events (
    rule_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(rule_id, event_id),
    FOREIGN KEY(rule_id) REFERENCES memory_forget_claim_rules(rule_id)
        ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_memory_forget_evidence_event
    ON memory_forget_evidence_events(event_id, rule_id);

CREATE TABLE IF NOT EXISTS memory_correction_forget_barriers (
    correction_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(correction_id, rule_id),
    FOREIGN KEY(correction_id) REFERENCES memory_corrections(correction_id)
        ON DELETE CASCADE,
    FOREIGN KEY(rule_id) REFERENCES memory_forget_claim_rules(rule_id)
        ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_memory_correction_forget_barrier_rule
    ON memory_correction_forget_barriers(rule_id, correction_id);
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_memory_correction_forget_barrier_rule;
DROP INDEX IF EXISTS idx_memory_forget_evidence_event;
DROP INDEX IF EXISTS idx_memory_forget_claim_rules_lookup;
DROP TABLE IF EXISTS memory_correction_forget_barriers;
DROP TABLE IF EXISTS memory_forget_evidence_events;
DROP TABLE IF EXISTS memory_forget_claim_rules;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a newly created shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v18_persistent_forget_governance")
    try:
        _execute_script(connection, SCHEMA_SQL)
        _backfill_forget_governance(connection)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v18_persistent_forget_governance")
        connection.execute("RELEASE SAVEPOINT v18_persistent_forget_governance")
        raise
    connection.execute("RELEASE SAVEPOINT v18_persistent_forget_governance")


def downgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v18_persistent_forget_governance_down")
    try:
        retained_count = int(connection.execute("""
                SELECT
                    (SELECT COUNT(*) FROM memory_forget_claim_rules)
                  + (SELECT COUNT(*) FROM memory_forget_evidence_events)
                  + (SELECT COUNT(*) FROM memory_correction_forget_barriers)
                """).fetchone()[0])
        if retained_count:
            raise RuntimeError(
                "Cannot downgrade persistent forget governance with retained forget data"
            )
        _execute_script(connection, DROP_SQL)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v18_persistent_forget_governance_down")
        connection.execute("RELEASE SAVEPOINT v18_persistent_forget_governance_down")
        raise
    connection.execute("RELEASE SAVEPOINT v18_persistent_forget_governance_down")


def _backfill_forget_governance(connection: Any) -> None:
    sources = (
        (
            "assertion",
            """
            SELECT assertion_id AS record_id, claim_fingerprint, authority_ref,
                   entity_id, entity_type, target_entity_id, trait_name,
                   trait_value, slot_key,
                   evidence_events AS raw_evidence,
                   first_inferred_at AS first_at,
                   last_validated_at AS last_at,
                   updated_at
            FROM tom_trait_assertions
            WHERE authority_ref IN ('forget:entity', 'forget:time_range')
               OR (
                   status = 'archived'
                   AND valid_to IS NULL
                   AND (
                       TRIM(COALESCE(authority_ref, '')) = ''
                       OR authority_ref LIKE 'correction:%'
                   )
               )
            ORDER BY assertion_id
            """,
        ),
        (
            "edge",
            """
            SELECT triple_id AS record_id, claim_fingerprint, authority_ref,
                   status_reason,
                   subject_id, predicate, object_id, slot_key,
                   evidence_event_ids AS raw_evidence,
                   first_observed_at AS first_at,
                   last_observed_at AS last_at,
                   updated_at
            FROM knowledge_graph
            WHERE authority_ref IN ('forget:entity', 'forget:time_range')
               OR status_reason = 'user_forget'
            ORDER BY triple_id
            """,
        ),
    )
    for target_kind, query in sources:
        for row in _row_dicts(connection, query):
            _backfill_record(connection, target_kind=target_kind, row=row)


def _backfill_record(
    connection: Any,
    *,
    target_kind: str,
    row: dict[str, Any],
) -> None:
    record_id = str(row["record_id"])
    forget_kind = _legacy_forget_kind(row)
    claim_fingerprint = str(row.get("claim_fingerprint") or "").strip()
    if not claim_fingerprint:
        claim_fingerprint = f"forgotten_record:{target_kind}:{record_id}"
    semantic_fingerprint = _semantic_fingerprint(
        target_kind=target_kind,
        row=row,
        fallback=claim_fingerprint,
    )
    created_at = _required_float(
        row.get("updated_at"),
        field_name="updated_at",
        record_id=record_id,
    )
    effective_from: float | None = None
    effective_to: float | None = None
    if forget_kind == "time_range":
        first_at = _required_float(
            row.get("first_at"),
            field_name="first_at",
            record_id=record_id,
        )
        last_at = _required_float(
            row.get("last_at"),
            field_name="last_at",
            record_id=record_id,
        )
        effective_from = min(first_at, last_at)
        effective_to = max(first_at, last_at)

    rule_id = _forget_rule_id(
        target_kind=target_kind,
        claim_fingerprint=claim_fingerprint,
        forget_kind=forget_kind,
        effective_from=effective_from,
        effective_to=effective_to,
    )

    evidence_event_ids, evidence_fail_closed = _parse_evidence(row.get("raw_evidence"))
    connection.execute(
        """
        INSERT INTO memory_forget_claim_rules(
            rule_id, target_kind, claim_fingerprint, semantic_fingerprint, forget_kind,
            effective_from, effective_to, evidence_fail_closed, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(rule_id) DO UPDATE SET
            evidence_fail_closed = MAX(
                memory_forget_claim_rules.evidence_fail_closed,
                excluded.evidence_fail_closed
            ),
            created_at = MIN(memory_forget_claim_rules.created_at, excluded.created_at)
        """,
        (
            rule_id,
            target_kind,
            claim_fingerprint,
            semantic_fingerprint,
            forget_kind,
            effective_from,
            effective_to,
            int(evidence_fail_closed),
            created_at,
        ),
    )
    connection.executemany(
        """
        INSERT OR IGNORE INTO memory_forget_evidence_events(
            rule_id, event_id, created_at
        )
        VALUES (?, ?, ?)
        """,
        [(rule_id, event_id, created_at) for event_id in evidence_event_ids],
    )
    correction_rows = connection.execute(
        """
        SELECT correction_id
        FROM memory_corrections
        WHERE state = 'active' AND target_kind = ?
          AND (target_id = ? OR replacement_target_id = ?)
        ORDER BY correction_id
        """,
        (target_kind, record_id, record_id),
    ).fetchall()
    connection.executemany(
        """
        INSERT OR IGNORE INTO memory_correction_forget_barriers(
            correction_id, rule_id, created_at
        ) VALUES (?, ?, ?)
        """,
        [(str(correction[0]), rule_id, created_at) for correction in correction_rows],
    )


def _legacy_forget_kind(row: dict[str, Any]) -> str:
    authority_ref = str(row.get("authority_ref") or "").strip()
    if authority_ref in {"forget:entity", "forget:time_range"}:
        return authority_ref.removeprefix("forget:")

    # Legacy rows did not retain enough information to reconstruct the original
    # forget scope. An unbounded rule is the only privacy-safe interpretation.
    return "entity"


def _parse_evidence(raw: Any) -> tuple[tuple[str, ...], bool]:
    if raw is None:
        return (), True
    decoded = raw
    for _ in range(2):
        if not isinstance(decoded, str):
            break
        try:
            decoded = json.loads(decoded)
        except (json.JSONDecodeError, TypeError):
            return (), True
    if not isinstance(decoded, list):
        return (), True

    event_ids: list[str] = []
    malformed = False
    for item in decoded:
        if not isinstance(item, str) or not item.strip():
            malformed = True
            continue
        event_ids.append(item.strip())
    return tuple(dict.fromkeys(event_ids)), malformed


_WHITESPACE_RE = re.compile(r"\s+")


def _semantic_fingerprint(
    *,
    target_kind: str,
    row: dict[str, Any],
    fallback: str,
) -> str:
    slot_key = str(row.get("slot_key") or "").strip()
    if target_kind == "assertion":
        if not slot_key:
            slot_key = "assertion_slot_" + _stable_digest(
                row.get("entity_type"),
                row.get("entity_id"),
                row.get("trait_name"),
                row.get("target_entity_id"),
            )
        return "assertion_claim_" + _stable_digest(
            slot_key,
            "global",
            _canonical_claim_value(row.get("trait_value")),
        )
    if target_kind == "edge":
        if not slot_key:
            slot_key = "edge_slot_" + _stable_digest(
                row.get("subject_id"),
                row.get("predicate"),
                row.get("object_id"),
            )
        return "edge_claim_" + _stable_digest(
            slot_key,
            row.get("subject_id"),
            row.get("predicate"),
            row.get("object_id"),
            "global",
        )
    return fallback


def _canonical_claim_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text and text[0] in '[{"':
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        else:
            if isinstance(parsed, (dict, list)):
                return json.dumps(
                    parsed,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
    return _normalized_text(text)


def _stable_digest(*parts: Any) -> str:
    payload = "\x1f".join(_normalized_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return _WHITESPACE_RE.sub(" ", text).casefold()


def _required_float(value: Any, *, field_name: str, record_id: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Invalid {field_name} for forgotten memory record: {record_id}"
        ) from exc
    if not math.isfinite(parsed):
        raise RuntimeError(f"Invalid {field_name} for forgotten memory record: {record_id}")
    return parsed


def _forget_rule_id(
    *,
    target_kind: str,
    claim_fingerprint: str,
    forget_kind: str,
    effective_from: float | None,
    effective_to: float | None,
) -> str:
    payload = json.dumps(
        {
            "target_kind": target_kind,
            "claim_fingerprint": claim_fingerprint,
            "forget_kind": forget_kind,
            "effective_from": effective_from,
            "effective_to": effective_to,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"forget_rule_{uuid.uuid5(uuid.NAMESPACE_URL, payload).hex}"


def _row_dicts(connection: Any, query: str) -> list[dict[str, Any]]:
    cursor = connection.execute(query)
    columns = [str(item[0]) for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _execute_script(connection: Any, script: str) -> None:
    pending = ""
    for line in script.splitlines():
        pending = f"{pending}{line}\n"
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            if statement:
                connection.execute(statement)
            pending = ""
    if pending.strip():
        raise RuntimeError("Incomplete SQL in persistent forget governance migration")


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
