"""Add the normalized grounded Claim ledger for L2 projections."""

from __future__ import annotations

from alembic import op

revision = "v38_l2_grounded_claims"
down_revision = "v37_history_import_selection"
branch_labels = None
depends_on = None


CREATE_STATEMENTS = (
    """
CREATE TABLE IF NOT EXISTS l2_grounded_claims (
    claim_id TEXT PRIMARY KEY,
    identity_key TEXT NOT NULL UNIQUE,
    extractor_contract_version INTEGER NOT NULL,
    evidence_rule_version INTEGER NOT NULL,
    origin_attempt_key TEXT,
    profile_id TEXT,
    user_id TEXT,
    subject_ref TEXT,
    subject_type TEXT,
    canonical_predicate TEXT,
    fact_kind TEXT,
    object_type TEXT,
    polarity TEXT,
    specificity TEXT,
    confidence REAL,
    object_value_json TEXT,
    object_surface TEXT,
    temporal_cue TEXT,
    fact_valid_from REAL,
    fact_valid_to REAL,
    target_from REAL,
    target_to REAL,
    raw_time_frame_json TEXT,
    availability TEXT NOT NULL DEFAULT 'active'
        CHECK (availability IN ('active', 'forgotten')),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    forgotten_at REAL,
    forget_tombstone_key TEXT,
    CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    CHECK (object_value_json IS NULL OR json_valid(object_value_json)),
    CHECK (raw_time_frame_json IS NULL OR json_valid(raw_time_frame_json)),
    CHECK (fact_valid_from IS NULL OR fact_valid_to IS NULL OR fact_valid_from <= fact_valid_to),
    CHECK (target_from IS NULL OR target_to IS NULL OR target_from <= target_to),
    CHECK (
        availability = 'forgotten' OR (
            origin_attempt_key IS NOT NULL AND
            subject_ref IS NOT NULL AND
            subject_type IS NOT NULL AND
            canonical_predicate IS NOT NULL AND
            fact_kind IS NOT NULL AND
            object_type IS NOT NULL AND
            polarity IS NOT NULL AND
            specificity IS NOT NULL AND
            confidence IS NOT NULL AND
            temporal_cue IS NOT NULL
        )
    ),
    CHECK (
        availability = 'active' OR (
            origin_attempt_key IS NULL AND profile_id IS NULL AND user_id IS NULL AND
            subject_ref IS NULL AND subject_type IS NULL AND
            canonical_predicate IS NULL AND fact_kind IS NULL AND
            object_type IS NULL AND polarity IS NULL AND specificity IS NULL AND
            confidence IS NULL AND object_value_json IS NULL AND
            object_surface IS NULL AND temporal_cue IS NULL AND
            fact_valid_from IS NULL AND fact_valid_to IS NULL AND
            target_from IS NULL AND target_to IS NULL AND
            raw_time_frame_json IS NULL
        )
    )
)
""",
    """
CREATE INDEX IF NOT EXISTS idx_l2_grounded_claims_user
    ON l2_grounded_claims(user_id, availability, created_at)
""",
    """
CREATE INDEX IF NOT EXISTS idx_l2_grounded_claims_predicate
    ON l2_grounded_claims(canonical_predicate, availability, created_at)
""",
    """
CREATE TABLE IF NOT EXISTS l2_claim_evidence (
    claim_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    link_role TEXT NOT NULL
        CHECK (link_role IN ('supporting', 'antecedent')),
    required_for_grounding INTEGER NOT NULL DEFAULT 0
        CHECK (required_for_grounding IN (0, 1)),
    event_time REAL,
    timestamp_confidence TEXT NOT NULL,
    timestamp_quality TEXT NOT NULL,
    timestamp_anchor_source TEXT,
    evidence_rule_version INTEGER NOT NULL,
    evidence_mode TEXT NOT NULL,
    source_type TEXT,
    source_domain TEXT,
    author_type TEXT,
    evidence_class TEXT,
    evidence_locator_json TEXT,
    created_at REAL NOT NULL,
    CHECK (evidence_locator_json IS NULL OR json_valid(evidence_locator_json)),
    PRIMARY KEY (claim_id, event_id, link_role),
    FOREIGN KEY (claim_id) REFERENCES l2_grounded_claims(claim_id)
        ON DELETE CASCADE
)
""",
    """
CREATE INDEX IF NOT EXISTS idx_l2_claim_evidence_event
    ON l2_claim_evidence(event_id, claim_id)
""",
    """
CREATE INDEX IF NOT EXISTS idx_l2_claim_evidence_time
    ON l2_claim_evidence(claim_id, event_time)
""",
    """
CREATE TABLE IF NOT EXISTS l2_claim_entity_refs (
    claim_id TEXT NOT NULL,
    ref_role TEXT NOT NULL
        CHECK (ref_role IN ('subject', 'object', 'target')),
    entity_id TEXT NOT NULL,
    resolution_version INTEGER NOT NULL,
    created_at REAL NOT NULL,
    invalidated_at REAL,
    invalidated_reason TEXT,
    PRIMARY KEY (claim_id, ref_role, resolution_version),
    FOREIGN KEY (claim_id) REFERENCES l2_grounded_claims(claim_id)
        ON DELETE CASCADE
)
""",
    """
CREATE INDEX IF NOT EXISTS idx_l2_claim_entity_refs_entity
    ON l2_claim_entity_refs(entity_id, invalidated_at, claim_id)
""",
    """
CREATE TABLE IF NOT EXISTS l2_claim_projection_outcomes (
    outcome_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    attempt_key TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL DEFAULT '',
    target_slot_key TEXT,
    route_contract_version INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL,
    reason_code TEXT,
    details_json TEXT,
    created_at REAL NOT NULL,
    invalidated_at REAL,
    invalidated_reason TEXT,
    CHECK (details_json IS NULL OR json_valid(details_json)),
    UNIQUE (claim_id, attempt_key, target_kind, target_id),
    FOREIGN KEY (claim_id) REFERENCES l2_grounded_claims(claim_id)
        ON DELETE CASCADE
)
""",
    """
CREATE INDEX IF NOT EXISTS idx_l2_claim_outcomes_latest
    ON l2_claim_projection_outcomes(claim_id, target_kind, created_at DESC)
""",
    """
CREATE INDEX IF NOT EXISTS idx_l2_claim_outcomes_route
    ON l2_claim_projection_outcomes(target_kind, outcome,
                                    route_contract_version, invalidated_at, created_at)
""",
)

DROP_STATEMENTS = (
    "DROP INDEX IF EXISTS idx_l2_claim_outcomes_route",
    "DROP INDEX IF EXISTS idx_l2_claim_outcomes_latest",
    "DROP TABLE IF EXISTS l2_claim_projection_outcomes",
    "DROP INDEX IF EXISTS idx_l2_claim_entity_refs_entity",
    "DROP TABLE IF EXISTS l2_claim_entity_refs",
    "DROP INDEX IF EXISTS idx_l2_claim_evidence_time",
    "DROP INDEX IF EXISTS idx_l2_claim_evidence_event",
    "DROP TABLE IF EXISTS l2_claim_evidence",
    "DROP INDEX IF EXISTS idx_l2_grounded_claims_predicate",
    "DROP INDEX IF EXISTS idx_l2_grounded_claims_user",
    "DROP TABLE IF EXISTS l2_grounded_claims",
)

CREATE_SQL = ";\n".join(statement.strip() for statement in CREATE_STATEMENTS) + ";"


def upgrade() -> None:
    for statement in CREATE_STATEMENTS:
        op.execute(statement.strip())


def schema_sql_for_fresh_database() -> str:
    """Return the release schema for a fresh shared-memory database."""

    return CREATE_SQL


def downgrade() -> None:
    for statement in DROP_STATEMENTS:
        op.execute(statement)


__all__ = [
    "CREATE_SQL",
    "CREATE_STATEMENTS",
    "DROP_STATEMENTS",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
