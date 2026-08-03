"""Advance subject revisions when grounded Claim inputs change."""

from __future__ import annotations

from alembic import op

revision = "v41_l2_claim_subject_revisions"
down_revision = "v40_l2_entity_link_outbox"
branch_labels = None
depends_on = None


TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_l2_claim_subject_revision_insert
AFTER INSERT ON l2_grounded_claims
WHEN NEW.subject_ref IS NOT NULL
BEGIN
    INSERT INTO memory_subject_revisions(subject_key, revision, updated_at)
    VALUES (NEW.subject_ref, 1, NEW.updated_at)
    ON CONFLICT(subject_key) DO UPDATE SET
        revision = memory_subject_revisions.revision + 1,
        updated_at = excluded.updated_at;
END;

CREATE TRIGGER IF NOT EXISTS trg_l2_claim_subject_revision_update_old
AFTER UPDATE ON l2_grounded_claims
WHEN OLD.subject_ref IS NOT NULL
BEGIN
    INSERT INTO memory_subject_revisions(subject_key, revision, updated_at)
    VALUES (OLD.subject_ref, 1, NEW.updated_at)
    ON CONFLICT(subject_key) DO UPDATE SET
        revision = memory_subject_revisions.revision + 1,
        updated_at = excluded.updated_at;
END;

CREATE TRIGGER IF NOT EXISTS trg_l2_claim_subject_revision_update_new
AFTER UPDATE ON l2_grounded_claims
WHEN NEW.subject_ref IS NOT NULL
 AND (OLD.subject_ref IS NULL OR NEW.subject_ref != OLD.subject_ref)
BEGIN
    INSERT INTO memory_subject_revisions(subject_key, revision, updated_at)
    VALUES (NEW.subject_ref, 1, NEW.updated_at)
    ON CONFLICT(subject_key) DO UPDATE SET
        revision = memory_subject_revisions.revision + 1,
        updated_at = excluded.updated_at;
END;

CREATE TRIGGER IF NOT EXISTS trg_l2_claim_outcome_subject_revision_insert
AFTER INSERT ON l2_claim_projection_outcomes
BEGIN
    INSERT INTO memory_subject_revisions(subject_key, revision, updated_at)
    SELECT claim.subject_ref, 1, NEW.created_at
    FROM l2_grounded_claims AS claim
    WHERE claim.claim_id = NEW.claim_id
      AND claim.subject_ref IS NOT NULL
    ON CONFLICT(subject_key) DO UPDATE SET
        revision = memory_subject_revisions.revision + 1,
        updated_at = excluded.updated_at;
END;

CREATE TRIGGER IF NOT EXISTS trg_l2_claim_outcome_subject_revision_update
AFTER UPDATE ON l2_claim_projection_outcomes
BEGIN
    INSERT INTO memory_subject_revisions(subject_key, revision, updated_at)
    SELECT claim.subject_ref, 1,
           COALESCE(NEW.invalidated_at, NEW.created_at)
    FROM l2_grounded_claims AS claim
    WHERE claim.claim_id = NEW.claim_id
      AND claim.subject_ref IS NOT NULL
    ON CONFLICT(subject_key) DO UPDATE SET
        revision = memory_subject_revisions.revision + 1,
        updated_at = excluded.updated_at;
END;
"""

TRIGGER_NAMES = (
    "trg_l2_claim_subject_revision_insert",
    "trg_l2_claim_subject_revision_update_old",
    "trg_l2_claim_subject_revision_update_new",
    "trg_l2_claim_outcome_subject_revision_insert",
    "trg_l2_claim_outcome_subject_revision_update",
)


def upgrade() -> None:
    op.get_bind().connection.executescript(TRIGGER_SQL)


def schema_sql_for_fresh_database() -> str:
    """Return the release schema addition for a fresh shared-memory database."""

    return TRIGGER_SQL


def downgrade() -> None:
    for trigger_name in reversed(TRIGGER_NAMES):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")


__all__ = [
    "TRIGGER_NAMES",
    "TRIGGER_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
