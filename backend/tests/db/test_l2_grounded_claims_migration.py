"""Schema contract for the normalized L2 grounded Claim ledger."""

from __future__ import annotations

import sqlite3

from _shared.memory_schema import MEMORY_SHARED_MIGRATIONS
from magi.db.migrations.memory_shared.versions.v38_l2_grounded_claims import (
    CREATE_SQL,
    revision,
)


def test_grounded_claim_migration_precedes_release_head() -> None:
    claim_index = MEMORY_SHARED_MIGRATIONS.index("v38_l2_grounded_claims.py")
    assert MEMORY_SHARED_MIGRATIONS[claim_index : claim_index + 5] == (
        "v38_l2_grounded_claims.py",
        "v39_l2_projection_leases.py",
        "v40_l2_entity_link_outbox.py",
        "v41_l2_claim_subject_revisions.py",
        "v42_l2_projection_batch_descriptors.py",
    )
    assert revision == "v38_l2_grounded_claims"


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
