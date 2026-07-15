"""Backfill conflict-aware relationship governance slots.

Revision ID: v6_relationship_governance_slots
Revises: v5_assertion_scope_uniqueness
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

from alembic import op

revision = "v6_relationship_governance_slots"
down_revision = "v5_assertion_scope_uniqueness"
branch_labels = None
depends_on = None


SCHEMA_SQL = "SELECT 1;"
DROP_SQL = "SELECT 1;"


def _normalized_text(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).strip().split()).casefold()


def _digest(*parts: Any) -> str:
    payload = "\x1f".join(_normalized_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row_dicts(connection: Any, query: str) -> list[dict[str, Any]]:
    cursor = connection.execute(query)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _rules(connection: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in _row_dicts(connection, "SELECT * FROM graph_conflict_rules"):
        result[str(row["predicate"])] = row
    return result


def _slot_key(row: dict[str, Any], rules: dict[str, dict[str, Any]]) -> str:
    predicate = str(row["predicate"])
    object_id = str(row["object_id"])
    rule = rules.get(predicate, {})
    exclusive_group = str(rule.get("exclusive_group") or "").strip()
    predicate_slot = ""
    if exclusive_group:
        predicate_slot = f"exclusive:{exclusive_group}"
    else:
        raw_opposites = rule.get("opposite_predicates") or "[]"
        try:
            opposites = json.loads(str(raw_opposites))
        except json.JSONDecodeError:
            opposites = []
        if opposites:
            family = ":".join(sorted({predicate, *(str(item) for item in opposites)}))
            predicate_slot = f"opposites:{family}:{object_id}"
    if predicate_slot:
        return f"edge_slot_{_digest(row['subject_id'], predicate_slot)}"
    return f"edge_slot_{_digest(row['subject_id'], predicate, object_id)}"


def _claim_fingerprint(row: dict[str, Any], slot_key: str) -> str:
    return "edge_claim_" + _digest(
        slot_key,
        row["subject_id"],
        row["predicate"],
        row["object_id"],
        row.get("scope_key") or "global",
    )


def _backfill(connection: Any) -> None:
    rules = _rules(connection)
    identities: dict[str, tuple[str, str]] = {}
    for row in _row_dicts(connection, "SELECT * FROM knowledge_graph"):
        triple_id = str(row["triple_id"])
        slot_key = _slot_key(row, rules)
        claim_fingerprint = _claim_fingerprint(row, slot_key)
        identities[triple_id] = (slot_key, claim_fingerprint)
        connection.execute(
            "UPDATE knowledge_graph SET slot_key = ?, claim_fingerprint = ? WHERE triple_id = ?",
            (slot_key, claim_fingerprint, triple_id),
        )
        connection.execute(
            """
            UPDATE knowledge_graph_versions
            SET slot_key = ?, claim_fingerprint = ?
            WHERE triple_id = ?
            """,
            (slot_key, claim_fingerprint, triple_id),
        )

    corrections = _row_dicts(
        connection,
        "SELECT * FROM memory_corrections WHERE target_kind = 'edge'",
    )
    for correction in corrections:
        correction_id = str(correction["correction_id"])
        target_identity = identities.get(str(correction["target_id"]))
        if target_identity is not None:
            connection.execute(
                """
                UPDATE memory_corrections
                SET slot_key = ?, claim_fingerprint = ?
                WHERE correction_id = ?
                """,
                (*target_identity, correction_id),
            )
            connection.execute(
                """
                UPDATE memory_correction_rules
                SET slot_key = ?, claim_fingerprint = ?
                WHERE correction_id = ?
                  AND rule_kind IN ('block_claim', 'close_before', 'scope_only')
                """,
                (*target_identity, correction_id),
            )
        replacement_identity = identities.get(str(correction.get("replacement_target_id") or ""))
        if replacement_identity is not None:
            connection.execute(
                """
                UPDATE memory_correction_rules
                SET slot_key = ?, claim_fingerprint = ?
                WHERE correction_id = ? AND rule_kind = 'authoritative_slot'
                """,
                (*replacement_identity, correction_id),
            )


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.executescript(SCHEMA_SQL)
    _backfill(connection)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
