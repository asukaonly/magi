"""Regression tests for memory correction schema backfill."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import sqlite_vec
from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.memory.l2.store import L2CognitionStore


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
        correction_evidence = connection.execute(
            """
            SELECT target_kind, event_id
            FROM memory_correction_evidence_events
            ORDER BY target_kind
            """
        ).fetchall()
        assert correction_evidence == [
            ("assertion", "event-1"),
            ("edge", "event-1"),
        ]
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


def test_relationship_version_snapshot_migration_quarantines_incomplete_history(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    config = _build_config(target, db_path)
    command.upgrade(config, "v9_memory_clear_generation")

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO knowledge_graph(
                triple_id, subject_id, subject_type, predicate, object_id, object_type,
                fact_kind, confidence, evidence_event_ids, first_observed_at,
                last_observed_at, source_type, extraction_method, valid_from, status,
                created_at, updated_at, evidence_class, slot_key, claim_fingerprint,
                scope_key, scope_json
            ) VALUES (
                'triple-legacy', 'user:u1', 'user', 'CURRENT_LIVES_IN',
                'place:shanghai', 'place', 'explicit_fact', 0.8, '["event-1"]',
                10, 100, 'conversation', 'explicit', 100, 'active', 10, 100,
                'observed_activity', 'slot-city', 'claim-current',
                'global', '{}'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO knowledge_graph_versions(
                version_id, triple_id, previous_version_id, slot_key,
                claim_fingerprint, subject_id, subject_type, predicate, object_id,
                object_type, fact_kind, confidence, evidence_event_ids,
                evidence_text, status, valid_from, valid_to, scope_key, scope_json,
                authority_ref, correction_id, created_at
            ) VALUES (
                'version-legacy', 'triple-legacy', NULL, 'slot-city',
                'claim-global', 'user:u1', 'user', 'CURRENT_LIVES_IN',
                'place:shanghai', 'place', 'explicit_fact', 0.8, '["event-1"]',
                '', 'active', 10, NULL, 'global', '{}', NULL, NULL, 20
            )
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT governance_complete, evidence_class, expires_at
            FROM knowledge_graph_versions
            WHERE version_id = 'version-legacy'
            """
        ).fetchone() == (0, None, None)

    store = L2CognitionStore(db_path=str(db_path))
    historical = asyncio.run(
        store.list_current_relationships(
            subject_id="user:u1",
            evidence_classes=["calendar_commitment"],
            effective_at=50,
        )
    )
    assert historical == []

    asyncio.run(store.reject_edge(triple_id="triple-legacy"))
    assert asyncio.run(
        store.active_correction_evidence_event_ids(["event-1"])
    ) == {"event-1"}
    unavailable_legacy_history = asyncio.run(
        store.list_current_relationships(
            subject_id="user:u1",
            evidence_classes=["observed_activity"],
            effective_at=50,
        )
    )
    assert unavailable_legacy_history == []
    historical_after_new_write = asyncio.run(
        store.list_current_relationships(
            subject_id="user:u1",
            evidence_classes=["observed_activity"],
            effective_at=150,
        )
    )
    assert [item["triple_id"] for item in historical_after_new_write] == [
        "triple-legacy"
    ]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*) FROM knowledge_graph_versions
            WHERE triple_id = 'triple-legacy' AND governance_complete = 1
            """
        ).fetchone() == (2,)


def test_correction_evidence_migration_fails_closed_on_malformed_json(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    config = _build_config(target, db_path)
    command.upgrade(config, "v10_relationship_version_snapshot")

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                state, created_at
            ) VALUES (
                'correction-invalid-evidence', 'request-invalid-evidence',
                'user:u1', 'assertion', 'assert-invalid', 'slot-invalid',
                'claim-invalid', 'record_error',
                '{"evidence_events":"[broken"}', 'active', 100
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                state, created_at
            ) VALUES (?, ?, 'user:u1', 'assertion', ?, ?, ?, 'record_error', ?, 'active', 100)
            """,
            [
                (
                    "correction-object-evidence",
                    "request-object-evidence",
                    "assert-object",
                    "slot-object",
                    "claim-object",
                    '{"evidence_events":{"event_id":"candidate-object"}}',
                ),
                (
                    "correction-number-evidence",
                    "request-number-evidence",
                    "assert-number",
                    "slot-number",
                    "claim-number",
                    '{"evidence_events":123}',
                ),
                (
                    "correction-array-object-evidence",
                    "request-array-object-evidence",
                    "assert-array-object",
                    "slot-array-object",
                    "claim-array-object",
                    '{"evidence_events":["candidate-valid",{"event_id":"candidate-bad"}]}',
                ),
            ],
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        sentinels = connection.execute(
            """
            SELECT correction_id
            FROM memory_correction_evidence_events
            WHERE event_id = '*'
            ORDER BY correction_id
            """
        ).fetchall()
        assert sentinels == [
            ("correction-array-object-evidence",),
            ("correction-invalid-evidence",),
            ("correction-number-evidence",),
            ("correction-object-evidence",),
        ]
    store = L2CognitionStore(db_path=str(db_path))
    assert asyncio.run(
        store.active_correction_evidence_event_ids(["candidate-a", "candidate-b"])
    ) == {"candidate-a", "candidate-b"}


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
