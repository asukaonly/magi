"""Schema contract for the normalized L2 grounded Claim ledger."""

from __future__ import annotations

import sqlite3

from magi.db.migrations.memory_shared.versions.v38_l2_grounded_claims import (
    CREATE_SQL,
)


def test_grounded_claim_schema_separates_semantics_evidence_and_outcomes() -> None:
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(CREATE_SQL)
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {
            "l2_grounded_claims",
            "l2_claim_evidence",
            "l2_claim_entity_refs",
            "l2_claim_projection_outcomes",
        } <= tables

        claim_columns = {
            row[1]: row[2]
            for row in db.execute("PRAGMA table_info(l2_grounded_claims)").fetchall()
        }
        assert claim_columns["fact_valid_from"] == "REAL"
        assert claim_columns["target_to"] == "REAL"
        assert "route_key" not in claim_columns

        evidence_pk = {
            row[1]: row[5]
            for row in db.execute("PRAGMA table_info(l2_claim_evidence)").fetchall()
            if row[5]
        }
        assert evidence_pk == {"claim_id": 1, "event_id": 2, "link_role": 3}

        outcome_columns = {
            row[1]
            for row in db.execute(
                "PRAGMA table_info(l2_claim_projection_outcomes)"
            ).fetchall()
        }
        assert {"invalidated_at", "invalidated_reason"} <= outcome_columns
    finally:
        db.close()
