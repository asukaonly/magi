"""Schema contracts for Claim-driven subject revision invalidation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from magi.db.migrations.memory_shared.versions.v41_l2_claim_subject_revisions import (
    TRIGGER_NAMES,
)
from magi.db.runner import MIGRATION_TARGETS, _build_config

V40_REVISION = "v40_l2_entity_link_outbox"
V41_REVISION = "v41_l2_claim_subject_revisions"


def _memory_config(db_path: Path):  # type: ignore[no-untyped-def]
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def _insert_claim(connection: sqlite3.Connection, *, claim_id: str, now: float) -> None:
    connection.execute(
        """
        INSERT INTO l2_grounded_claims(
            claim_id, identity_key, extractor_contract_version,
            evidence_rule_version, origin_attempt_key, user_id,
            subject_ref, subject_type, canonical_predicate, fact_kind,
            object_type, polarity, specificity, confidence, temporal_cue,
            availability, created_at, updated_at
        ) VALUES (?, ?, 1, 1, 'attempt:1', 'u1', 'user:u1', 'user',
                  'LIKES', 'preference', 'concept', 'positive', 'specific',
                  0.9, 'stable', 'active', ?, ?)
        """,
        (claim_id, f"identity:{claim_id}", now, now),
    )


def _revision(connection: sqlite3.Connection, subject_key: str = "user:u1") -> int:
    row = connection.execute(
        "SELECT revision FROM memory_subject_revisions WHERE subject_key = ?",
        (subject_key,),
    ).fetchone()
    return int(row[0]) if row is not None else 0


def test_claim_and_route_changes_advance_durable_subject_revision(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V41_REVISION)

    with sqlite3.connect(db_path) as connection:
        _insert_claim(connection, claim_id="claim-1", now=10.0)
        assert _revision(connection) == 1

        connection.execute(
            """
            INSERT INTO l2_claim_projection_outcomes(
                outcome_id, claim_id, attempt_key, target_kind, target_id,
                route_contract_version, outcome, created_at
            ) VALUES ('outcome-1', 'claim-1', 'attempt:1', 'assertion',
                      'assertion-1', 1, 'projected', 11.0)
            """
        )
        assert _revision(connection) == 2

        connection.execute(
            """
            UPDATE l2_claim_projection_outcomes
            SET invalidated_at = 12.0, invalidated_reason = 'route_changed'
            WHERE outcome_id = 'outcome-1'
            """
        )
        assert _revision(connection) == 3

        connection.execute(
            """
            UPDATE l2_grounded_claims
            SET origin_attempt_key = NULL, profile_id = NULL, user_id = NULL,
                subject_ref = NULL, subject_type = NULL,
                canonical_predicate = NULL, fact_kind = NULL,
                object_type = NULL, polarity = NULL, specificity = NULL,
                confidence = NULL, object_value_json = NULL,
                object_surface = NULL, temporal_cue = NULL,
                fact_valid_from = NULL, fact_valid_to = NULL,
                target_from = NULL, target_to = NULL,
                raw_time_frame_json = NULL, availability = 'forgotten',
                forgotten_at = 13.0, forget_tombstone_key = 'forget:1',
                updated_at = 13.0
            WHERE claim_id = 'claim-1'
            """
        )
        assert _revision(connection) == 4


def test_claim_subject_revision_migration_drops_only_its_triggers(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V41_REVISION)

    command.downgrade(config, V40_REVISION)

    with sqlite3.connect(db_path) as connection:
        trigger_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            ).fetchall()
        }
        assert set(TRIGGER_NAMES).isdisjoint(trigger_names)
        _insert_claim(connection, claim_id="claim-after-downgrade", now=20.0)
        assert _revision(connection) == 0
