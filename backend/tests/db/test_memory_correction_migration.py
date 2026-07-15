"""Regression tests for memory correction schema backfill."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec
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
                'triple-old', 'user:local_user', 'user', 'CURRENT_LIVES_IN', 'place:hangzhou',
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
        edge_governance = connection.execute(
            """
            SELECT corrections.slot_key, corrections.claim_fingerprint,
                   rules.slot_key, rules.claim_fingerprint,
                   versions.slot_key, versions.claim_fingerprint
            FROM memory_corrections AS corrections
            JOIN memory_correction_rules AS rules
              ON rules.correction_id = corrections.correction_id
            JOIN knowledge_graph_versions AS versions
              ON versions.triple_id = corrections.target_id
            WHERE corrections.target_kind = 'edge'
            """
        ).fetchone()
        assert edge_governance == (
            edge[0],
            edge[1],
            edge[0],
            edge[1],
            edge[0],
            edge[1],
        )
        assert connection.execute(
            "SELECT revision FROM memory_subject_revisions WHERE subject_key = 'user:local_user'"
        ).fetchone() == (1,)


def test_legacy_l3_insights_without_dependencies_are_quarantined(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    config = _build_config(target, db_path)
    command.upgrade(config, "v6_relationship_governance_slots")

    with sqlite3.connect(db_path) as connection:
        summary_rows = [
            (
                "legacy-unknown",
                "insight",
                "state_change",
                "A legacy claim with unknown dependencies.",
                "legacy:unknown",
            ),
            (
                "legacy-linked",
                "insight",
                "state_change",
                "A legacy claim with known dependencies.",
                "legacy:linked",
            ),
            (
                "legacy-orphan",
                "insight",
                "state_change",
                "A legacy claim with an orphaned dependency.",
                "legacy:orphan",
            ),
            (
                "legacy-temporal",
                "temporal",
                "day",
                "A source-backed temporal recap.",
                None,
            ),
        ]
        connection.executemany(
            """
            INSERT INTO summaries(
                summary_id, summary_type, summary_category, period_start, period_end,
                content, source_event_ids, source_event_count, insight_key,
                embedding_status, embedding_profile_id, embedding_chunk_count,
                last_embedded_at, source_revision, created_at, updated_at
            ) VALUES (?, ?, ?, 1, 2, ?, '["event-1"]', 1, ?, 'ready',
                      'profile-1', 1, 2, 0, 1, 2)
            """,
            summary_rows,
        )
        connection.execute(
            """
            INSERT INTO tom_trait_assertions(
                assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                confidence_score, evidence_events, volatility_index, source_domain,
                inference_depth, validation_state, first_inferred_at, last_validated_at,
                target_entity_id, target_entity_type, target_scope, temporal_scope,
                status, created_at, updated_at
            ) VALUES (
                'assertion-1', 'user:local_user', 'user', 'identity_profile',
                'identity.location.home', 'Shanghai', 0.9, '["event-1"]', 0.1,
                'chat', 'explicit', 'stable', 1, 2, '', '', 'global',
                'stable', 'stable', 1, 2
            )
            """
        )
        connection.execute(
            """
            INSERT INTO memory_derivation_dependencies(
                artifact_kind, artifact_id, source_kind, source_id,
                subject_key, source_revision, created_at
            ) VALUES ('l3_insight', 'legacy-linked', 'assertion', 'assertion-1',
                      'user:local_user', 0, 2)
            """
        )
        connection.execute(
            """
            INSERT INTO memory_derivation_dependencies(
                artifact_kind, artifact_id, source_kind, source_id,
                subject_key, source_revision, created_at
            ) VALUES ('l3_insight', 'legacy-orphan', 'assertion', 'missing-assertion',
                      'user:local_user', 0, 2)
            """
        )
        connection.execute(
            """
            INSERT INTO l3_summary_chunks(
                chunk_id, summary_id, chunk_index, chunk_text,
                char_start, char_end, token_estimate, created_at, updated_at
            ) VALUES ('chunk-legacy', 'legacy-unknown', 0, 'legacy', 0, 6, 1, 1, 2)
            """
        )
        connection.enable_load_extension(True)
        try:
            connection.load_extension(sqlite_vec.loadable_path())
        finally:
            connection.enable_load_extension(False)
        connection.execute(
            """
            CREATE TABLE l3_summary_chunk_vectors (
                vec_rowid INTEGER PRIMARY KEY,
                chunk_id TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding_dim INTEGER NOT NULL,
                vec_table TEXT NOT NULL,
                metadata TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(chunk_id, embedding_model)
            )
            """
        )
        connection.execute(
            "CREATE VIRTUAL TABLE l3_summary_chunk_vec_test USING vec0(embedding float[2])"
        )
        connection.execute(
            "INSERT INTO l3_summary_chunk_vec_test(rowid, embedding) VALUES (1, ?)",
            (sqlite_vec.serialize_float32([1.0, 0.0]),),
        )
        connection.execute(
            """
            INSERT INTO l3_summary_chunk_vectors(
                vec_rowid, chunk_id, embedding_model, embedding_dim, vec_table,
                metadata, created_at, updated_at
            ) VALUES (1, 'chunk-legacy', 'test', 2, 'l3_summary_chunk_vec_test', NULL, 1, 2)
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        states = dict(
            connection.execute(
                "SELECT summary_id, derivation_state FROM summaries ORDER BY summary_id"
            ).fetchall()
        )
        assert states == {
            "legacy-linked": "current",
            "legacy-orphan": "stale",
            "legacy-temporal": "current",
            "legacy-unknown": "stale",
        }
        assert connection.execute(
            """
            SELECT embedding_status, embedding_profile_id,
                   embedding_chunk_count, last_embedded_at
            FROM summaries WHERE summary_id = 'legacy-unknown'
            """
        ).fetchone() == ("disabled", None, 0, None)
        assert connection.execute(
            "SELECT COUNT(*) FROM l3_summary_chunks WHERE summary_id = 'legacy-unknown'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM l3_summary_chunk_vectors WHERE chunk_id = 'chunk-legacy'"
        ).fetchone() == (0,)
        connection.enable_load_extension(True)
        try:
            connection.load_extension(sqlite_vec.loadable_path())
        finally:
            connection.enable_load_extension(False)
        assert connection.execute(
            "SELECT COUNT(*) FROM l3_summary_chunk_vec_test"
        ).fetchone() == (0,)
