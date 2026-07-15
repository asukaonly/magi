"""Regression tests for memory correction schema backfill."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config


def test_memory_correction_migration_backfills_rejected_claims(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    config = _build_config(target, db_path)
    command.upgrade(config, "v3_experience_draft_cover")

    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            INSERT INTO tom_trait_assertions(
                assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                confidence_score, evidence_events, volatility_index, source_domain,
                inference_depth, validation_state, first_inferred_at, last_validated_at,
                target_entity_id, target_entity_type, target_scope, temporal_scope,
                status, created_at, updated_at
            ) VALUES (
                'assert-old', 'user:local_user', 'user', 'identity_profile',
                'identity.location.home', 'Hangzhou', 0.1, '["event-1"]', 0.1,
                'chat', 'explicit', 'user_rejected', 10, 20, '', '', 'global',
                'stable', 'user_rejected', 10, 20
            )
            """)
        connection.execute("""
            INSERT INTO knowledge_graph(
                triple_id, subject_id, subject_type, predicate, object_id, object_type,
                fact_kind, confidence, evidence_event_ids, observation_count,
                first_observed_at, last_observed_at, status, created_at, updated_at
            ) VALUES (
                'triple-old', 'user:local_user', 'user', 'LIVES_IN', 'place:hangzhou',
                'place', 'explicit_fact', 0.1, '["event-1"]', 1, 10, 20,
                'user_rejected', 10, 20
            )
            """)
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assertion = connection.execute("""
            SELECT slot_key, claim_fingerprint, version_root_id, valid_from, scope_key
            FROM tom_trait_assertions WHERE assertion_id = 'assert-old'
            """).fetchone()
        assert assertion is not None
        assert assertion[0].startswith("assertion_slot_")
        assert assertion[1].startswith("assertion_claim_")
        assert assertion[2:] == ("assert-old", 10.0, "global")

        edge = connection.execute(
            "SELECT slot_key, claim_fingerprint FROM knowledge_graph WHERE triple_id = 'triple-old'"
        ).fetchone()
        assert edge is not None
        assert edge[0].startswith("edge_slot_")
        assert edge[1].startswith("edge_claim_")
        assert connection.execute(
            "SELECT COUNT(*) FROM knowledge_graph_versions WHERE triple_id = 'triple-old'"
        ).fetchone() == (1,)

        corrections = connection.execute(
            "SELECT target_kind, target_id FROM memory_corrections ORDER BY target_kind"
        ).fetchall()
        assert corrections == [("assertion", "assert-old"), ("edge", "triple-old")]
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_correction_rules WHERE rule_kind = 'block_claim'"
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT revision FROM memory_subject_revisions WHERE subject_key = 'user:local_user'"
        ).fetchone() == (1,)
