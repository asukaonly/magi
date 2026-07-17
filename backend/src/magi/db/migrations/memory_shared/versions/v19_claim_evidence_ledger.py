"""Persist claim-to-event evidence observed by L2 memory records.

Revision ID: v19_claim_evidence_ledger
Revises: v18_persistent_forget_governance
"""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

from alembic import op

revision = "v19_claim_evidence_ledger"
down_revision = "v18_persistent_forget_governance"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_claim_evidence_events (
    target_kind TEXT NOT NULL CHECK(target_kind IN ('assertion', 'edge')),
    claim_fingerprint TEXT NOT NULL,
    event_id TEXT NOT NULL,
    observed_at REAL NOT NULL,
    observed_from REAL NOT NULL,
    observed_to REAL NOT NULL,
    observed_at_is_approximate INTEGER NOT NULL DEFAULT 1
        CHECK(observed_at_is_approximate IN (0, 1)),
    created_at REAL NOT NULL,
    CHECK(observed_from <= observed_to),
    PRIMARY KEY(target_kind, claim_fingerprint, event_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_claim_evidence_claim_observed
    ON memory_claim_evidence_events(
        target_kind, claim_fingerprint, observed_from, observed_to, event_id
    );
CREATE INDEX IF NOT EXISTS idx_memory_claim_evidence_event
    ON memory_claim_evidence_events(event_id, target_kind, claim_fingerprint);
CREATE INDEX IF NOT EXISTS idx_memory_claim_evidence_approximate_event
    ON memory_claim_evidence_events(event_id)
    WHERE observed_at_is_approximate = 1;
"""


DROP_SQL = """
DROP INDEX IF EXISTS idx_memory_claim_evidence_approximate_event;
DROP INDEX IF EXISTS idx_memory_claim_evidence_event;
DROP INDEX IF EXISTS idx_memory_claim_evidence_claim_observed;
DROP TABLE IF EXISTS memory_claim_evidence_events;
"""


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a newly created shared-memory database."""
    return SCHEMA_SQL


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v19_claim_evidence_ledger")
    try:
        _execute_script(connection, SCHEMA_SQL)
        _backfill_claim_evidence(connection)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v19_claim_evidence_ledger")
        connection.execute("RELEASE SAVEPOINT v19_claim_evidence_ledger")
        raise
    connection.execute("RELEASE SAVEPOINT v19_claim_evidence_ledger")


def downgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v19_claim_evidence_ledger_down")
    try:
        retained_count = int(
            connection.execute("SELECT COUNT(*) FROM memory_claim_evidence_events").fetchone()[0]
        )
        if retained_count:
            raise RuntimeError("Cannot downgrade claim evidence ledger with retained evidence data")
        _execute_script(connection, DROP_SQL)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v19_claim_evidence_ledger_down")
        connection.execute("RELEASE SAVEPOINT v19_claim_evidence_ledger_down")
        raise
    connection.execute("RELEASE SAVEPOINT v19_claim_evidence_ledger_down")


def _backfill_claim_evidence(connection: Any) -> None:
    sources = (
        (
            "assertion",
            """
            SELECT claim_fingerprint, evidence_events AS raw_evidence,
                   last_validated_at AS observed_at,
                   first_inferred_at AS observed_from,
                   last_validated_at AS observed_to,
                   created_at
            FROM tom_trait_assertions
            ORDER BY assertion_id
            """,
        ),
        (
            "edge",
            """
            SELECT claim_fingerprint, evidence_event_ids AS raw_evidence,
                   last_observed_at AS observed_at,
                   first_observed_at AS observed_from,
                   last_observed_at AS observed_to,
                   created_at
            FROM knowledge_graph
            ORDER BY triple_id
            """,
        ),
        (
            "edge",
            """
            SELECT claim_fingerprint, evidence_event_ids AS raw_evidence,
                   COALESCE(
                       last_observed_at,
                       first_observed_at,
                       valid_from,
                       edge_created_at,
                       created_at
                   ) AS observed_at,
                   COALESCE(
                       first_observed_at,
                       valid_from,
                       edge_created_at,
                       created_at
                   ) AS observed_from,
                   COALESCE(
                       last_observed_at,
                       valid_to,
                       first_observed_at,
                       valid_from,
                       edge_created_at,
                       created_at
                   ) AS observed_to,
                   COALESCE(edge_created_at, created_at) AS created_at
            FROM knowledge_graph_versions
            ORDER BY created_at, version_id
            """,
        ),
    )
    for target_kind, query in sources:
        for row in _row_dicts(connection, query):
            claim_fingerprint = str(row.get("claim_fingerprint") or "").strip()
            event_ids = _parse_evidence_event_ids(row.get("raw_evidence"))
            if not claim_fingerprint or not event_ids:
                continue
            observed_at = _required_finite_float(
                row.get("observed_at"),
                field_name="observed_at",
                claim_fingerprint=claim_fingerprint,
            )
            created_at = _required_finite_float(
                row.get("created_at"),
                field_name="created_at",
                claim_fingerprint=claim_fingerprint,
            )
            observed_from = _required_finite_float(
                row.get("observed_from"),
                field_name="observed_from",
                claim_fingerprint=claim_fingerprint,
            )
            observed_to = _required_finite_float(
                row.get("observed_to"),
                field_name="observed_to",
                claim_fingerprint=claim_fingerprint,
            )
            interval_start = min(observed_from, observed_to)
            interval_end = max(observed_from, observed_to)
            connection.executemany(
                """
                INSERT INTO memory_claim_evidence_events(
                    target_kind, claim_fingerprint, event_id,
                    observed_at, observed_from, observed_to,
                    observed_at_is_approximate, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(target_kind, claim_fingerprint, event_id) DO UPDATE SET
                    observed_at = MIN(
                        memory_claim_evidence_events.observed_at,
                        excluded.observed_at
                    ),
                    observed_from = MIN(
                        memory_claim_evidence_events.observed_from,
                        excluded.observed_from
                    ),
                    observed_to = MAX(
                        memory_claim_evidence_events.observed_to,
                        excluded.observed_to
                    ),
                    observed_at_is_approximate = 1,
                    created_at = MIN(
                        memory_claim_evidence_events.created_at,
                        excluded.created_at
                    )
                """,
                [
                    (
                        target_kind,
                        claim_fingerprint,
                        event_id,
                        observed_at,
                        interval_start,
                        interval_end,
                        created_at,
                    )
                    for event_id in event_ids
                ],
            )


def _parse_evidence_event_ids(raw: Any) -> tuple[str, ...] | None:
    decoded = raw
    for _ in range(2):
        if not isinstance(decoded, str):
            break
        try:
            decoded = json.loads(decoded)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(decoded, list):
        return None
    if any(not isinstance(item, str) or not item.strip() for item in decoded):
        return None
    return tuple(dict.fromkeys(item.strip() for item in decoded))


def _required_finite_float(
    value: Any,
    *,
    field_name: str,
    claim_fingerprint: str,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid {field_name} for claim evidence: {claim_fingerprint}") from exc
    if not math.isfinite(parsed):
        raise RuntimeError(f"Invalid {field_name} for claim evidence: {claim_fingerprint}")
    return parsed


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
        raise RuntimeError("Incomplete SQL in claim evidence ledger migration")


__all__ = [
    "DROP_SQL",
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
