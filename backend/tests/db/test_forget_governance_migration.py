"""Regression coverage for persistent user-forget governance."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command

from _shared.memory_schema import apply_memory_shared_schema
from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.memory.l2.corrections.fingerprints import (
    assertion_claim_fingerprint,
    relationship_claim_fingerprint,
)

V17_REVISION = "v17_scheduled_correction_cancellation"
V18_REVISION = "v18_persistent_forget_governance"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def _insert_assertion(
    connection: sqlite3.Connection,
    *,
    assertion_id: str,
    claim_fingerprint: str,
    authority_ref: str | None,
    raw_evidence: str,
    first_at: float,
    last_at: float,
    updated_at: float | str,
    status: str = "archived",
    valid_to: float | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO tom_trait_assertions(
            assertion_id, entity_id, entity_type, trait_family, trait_name,
            trait_value, confidence_score, evidence_events, volatility_index,
            source_domain, inference_depth, validation_state, first_inferred_at,
            last_validated_at, target_entity_id, target_entity_type, target_scope,
            temporal_scope, status, natural_summary, created_at, updated_at,
            slot_key, claim_fingerprint, authority_ref, version_root_id,
            valid_from, valid_to, scope_key, scope_json
        ) VALUES (?, ?, 'entity', 'preference', ?, ?, 0.9, ?, 0.1,
                  'chat', 'explicit', 'stable', ?, ?, '', '', 'global',
                  'stable', ?, '', ?, ?, ?, ?, ?, ?, ?, ?, 'global', '{}')
        """,
        (
            assertion_id,
            f"entity:{assertion_id}",
            f"trait:{assertion_id}",
            f"value:{assertion_id}",
            raw_evidence,
            first_at,
            last_at,
            status,
            first_at,
            updated_at,
            f"slot:{assertion_id}",
            claim_fingerprint,
            authority_ref,
            assertion_id,
            first_at,
            valid_to,
        ),
    )


def _insert_edge(
    connection: sqlite3.Connection,
    *,
    triple_id: str,
    claim_fingerprint: str,
    authority_ref: str | None,
    raw_evidence: str,
    first_at: float,
    last_at: float,
    updated_at: float,
    status_reason: str | None = "user_forget",
) -> None:
    connection.execute(
        """
        INSERT INTO knowledge_graph(
            triple_id, subject_id, subject_type, predicate, object_id, object_type,
            fact_kind, confidence, evidence_event_ids, observation_count,
            first_observed_at, last_observed_at, source_type, extraction_method,
            valid_from, status, status_reason, created_at, updated_at,
            evidence_class, slot_key, claim_fingerprint, authority_ref,
            scope_key, scope_json
        ) VALUES (?, 'user:u1', 'user', ?, ?, 'entity', 'explicit_fact',
                  0.9, ?, 1, ?, ?, 'conversation', 'explicit', ?, 'archived',
                  ?, ?, ?, 'user_self_report', ?, ?, ?, 'global', '{}')
        """,
        (
            triple_id,
            f"REL_{triple_id.upper().replace('-', '_')}",
            f"object:{triple_id}",
            raw_evidence,
            first_at,
            last_at,
            first_at,
            status_reason,
            first_at,
            updated_at,
            f"slot:{triple_id}",
            claim_fingerprint,
            authority_ref,
        ),
    )


def _insert_correction(
    connection: sqlite3.Connection,
    *,
    correction_id: str,
    target_kind: str,
    target_id: str,
    replacement_target_id: str | None = None,
    state: str = "active",
) -> None:
    connection.execute(
        """
        INSERT INTO memory_corrections(
            correction_id, request_id, actor_id, target_kind, target_id,
            slot_key, claim_fingerprint, correction_kind, before_json,
            replacement_target_id, state, created_at, reverted_at
        ) VALUES (?, ?, 'user:u1', ?, ?, ?, ?, 'record_error', '{}',
                  ?, ?, 50, ?)
        """,
        (
            correction_id,
            f"request:{correction_id}",
            target_kind,
            target_id,
            f"slot:{correction_id}",
            f"claim:{correction_id}",
            replacement_target_id,
            state,
            60 if state == "reverted" else None,
        ),
    )


def test_forget_governance_migration_backfills_rules_evidence_and_barriers(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V17_REVISION)

    with sqlite3.connect(db_path) as connection:
        _insert_assertion(
            connection,
            assertion_id="assertion-entity",
            claim_fingerprint="claim-a",
            authority_ref="forget:entity",
            raw_evidence=json.dumps(["assertion-event", "*"]),
            first_at=10,
            last_at=20,
            updated_at=100,
        )
        _insert_edge(
            connection,
            triple_id="edge-time",
            claim_fingerprint="claim-b",
            authority_ref="forget:time_range",
            raw_evidence=json.dumps(json.dumps(["edge-event"])),
            first_at=160,
            last_at=100,
            updated_at=200,
        )
        _insert_assertion(
            connection,
            assertion_id="assertion-time-malformed",
            claim_fingerprint="claim-c",
            authority_ref="forget:time_range",
            raw_evidence=json.dumps(["mixed-event", 7, ""]),
            first_at=300,
            last_at=350,
            updated_at=400,
        )
        _insert_edge(
            connection,
            triple_id="edge-entity-malformed",
            claim_fingerprint="claim-d",
            authority_ref="forget:entity",
            raw_evidence="[broken",
            first_at=450,
            last_at=460,
            updated_at=500,
        )
        _insert_assertion(
            connection,
            assertion_id="assertion-unrelated-authority",
            claim_fingerprint="claim-e",
            authority_ref="forget:other",
            raw_evidence='["unrelated-event"]',
            first_at=600,
            last_at=610,
            updated_at=620,
        )
        _insert_correction(
            connection,
            correction_id="correction-assertion-target",
            target_kind="assertion",
            target_id="assertion-entity",
        )
        _insert_correction(
            connection,
            correction_id="correction-edge-replacement",
            target_kind="edge",
            target_id="edge-before-replacement",
            replacement_target_id="edge-time",
        )
        _insert_correction(
            connection,
            correction_id="correction-reverted",
            target_kind="assertion",
            target_id="assertion-time-malformed",
            state="reverted",
        )
        _insert_correction(
            connection,
            correction_id="correction-unrelated",
            target_kind="assertion",
            target_id="assertion-unrelated-authority",
        )
        connection.commit()

    command.upgrade(config, V18_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V18_REVISION,
        )
        assert (
            connection.execute("""
            SELECT target_kind, claim_fingerprint, forget_kind,
                   effective_from, effective_to, evidence_fail_closed, created_at
            FROM memory_forget_claim_rules
            ORDER BY claim_fingerprint
            """).fetchall()
            == [
                ("assertion", "claim-a", "entity", None, None, 0, 100.0),
                ("edge", "claim-b", "time_range", 100.0, 160.0, 0, 200.0),
                ("assertion", "claim-c", "time_range", 300.0, 350.0, 1, 400.0),
                ("edge", "claim-d", "entity", None, None, 1, 500.0),
            ]
        )
        assert (
            connection.execute("""
            SELECT rules.claim_fingerprint, evidence.event_id
            FROM memory_forget_evidence_events AS evidence
            JOIN memory_forget_claim_rules AS rules USING(rule_id)
            ORDER BY rules.claim_fingerprint, evidence.event_id
            """).fetchall()
            == [
                ("claim-a", "*"),
                ("claim-a", "assertion-event"),
                ("claim-b", "edge-event"),
                ("claim-c", "mixed-event"),
            ]
        )
        assert (
            connection.execute("""
            SELECT barriers.correction_id, rules.claim_fingerprint
            FROM memory_correction_forget_barriers AS barriers
            JOIN memory_forget_claim_rules AS rules USING(rule_id)
            ORDER BY barriers.correction_id
            """).fetchall()
            == [
                ("correction-assertion-target", "claim-a"),
                ("correction-edge-replacement", "claim-b"),
            ]
        )
        semantic_fingerprints = dict(connection.execute("""
                SELECT claim_fingerprint, semantic_fingerprint
                FROM memory_forget_claim_rules
                """).fetchall())

    assert semantic_fingerprints["claim-a"] == assertion_claim_fingerprint(
        slot_key_value="slot:assertion-entity",
        trait_value="value:assertion-entity",
    )
    assert semantic_fingerprints["claim-b"] == relationship_claim_fingerprint(
        slot_key_value="slot:edge-time",
        subject_id="user:u1",
        predicate="REL_EDGE_TIME",
        object_id="object:edge-time",
    )


def test_forget_governance_migration_recovers_legacy_forget_shapes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V17_REVISION)

    with sqlite3.connect(db_path) as connection:
        _insert_edge(
            connection,
            triple_id="edge-legacy-forgotten",
            claim_fingerprint="claim-legacy-edge",
            authority_ref=None,
            raw_evidence='["event-legacy-edge"]',
            first_at=10,
            last_at=20,
            updated_at=30,
        )
        _insert_assertion(
            connection,
            assertion_id="assertion-legacy-forgotten",
            claim_fingerprint="claim-legacy-assertion",
            authority_ref=None,
            raw_evidence='["event-legacy-assertion"]',
            first_at=40,
            last_at=50,
            updated_at=60,
        )
        _insert_assertion(
            connection,
            assertion_id="assertion-corrected-then-forgotten",
            claim_fingerprint="claim-corrected-then-forgotten",
            authority_ref="correction:legacy",
            raw_evidence='["event-corrected-then-forgotten"]',
            first_at=70,
            last_at=80,
            updated_at=90,
        )
        _insert_assertion(
            connection,
            assertion_id="assertion-correction-archive",
            claim_fingerprint="claim-correction-archive",
            authority_ref="correction:reverted",
            raw_evidence='["event-correction-archive"]',
            first_at=100,
            last_at=110,
            updated_at=120,
            valid_to=115,
        )
        _insert_assertion(
            connection,
            assertion_id="assertion-still-active",
            claim_fingerprint="claim-still-active",
            authority_ref=None,
            raw_evidence='["event-still-active"]',
            first_at=130,
            last_at=140,
            updated_at=150,
            status="active",
        )
        _insert_correction(
            connection,
            correction_id="correction-legacy-forgotten",
            target_kind="assertion",
            target_id="assertion-corrected-then-forgotten",
        )
        connection.commit()

    command.upgrade(config, V18_REVISION)

    with sqlite3.connect(db_path) as connection:
        rules = connection.execute("""
            SELECT target_kind, claim_fingerprint, forget_kind,
                   effective_from, effective_to, semantic_fingerprint
            FROM memory_forget_claim_rules
            ORDER BY claim_fingerprint
            """).fetchall()
        evidence = connection.execute("""
            SELECT rules.claim_fingerprint, evidence.event_id
            FROM memory_forget_evidence_events AS evidence
            JOIN memory_forget_claim_rules AS rules USING(rule_id)
            ORDER BY rules.claim_fingerprint
            """).fetchall()
        barriers = connection.execute("""
            SELECT correction_id
            FROM memory_correction_forget_barriers
            """).fetchall()

    assert [(row[0], row[1], row[2], row[3], row[4]) for row in rules] == [
        ("assertion", "claim-corrected-then-forgotten", "entity", None, None),
        ("assertion", "claim-legacy-assertion", "entity", None, None),
        ("edge", "claim-legacy-edge", "entity", None, None),
    ]
    assert evidence == [
        ("claim-corrected-then-forgotten", "event-corrected-then-forgotten"),
        ("claim-legacy-assertion", "event-legacy-assertion"),
        ("claim-legacy-edge", "event-legacy-edge"),
    ]
    assert barriers == [("correction-legacy-forgotten",)]
    assert rules[0][5] == assertion_claim_fingerprint(
        slot_key_value="slot:assertion-corrected-then-forgotten",
        trait_value="value:assertion-corrected-then-forgotten",
    )
    assert rules[2][5] == relationship_claim_fingerprint(
        slot_key_value="slot:edge-legacy-forgotten",
        subject_id="user:u1",
        predicate="REL_EDGE_LEGACY_FORGOTTEN",
        object_id="object:edge-legacy-forgotten",
    )


def test_forget_governance_migration_rolls_back_and_retries(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V17_REVISION)
    with sqlite3.connect(db_path) as connection:
        _insert_assertion(
            connection,
            assertion_id="assertion-broken-time",
            claim_fingerprint="claim-broken-time",
            authority_ref="forget:entity",
            raw_evidence='["event-broken-time"]',
            first_at=10,
            last_at=20,
            updated_at="not-a-time",
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="Invalid updated_at"):
        command.upgrade(config, V18_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V17_REVISION,
        )
        assert connection.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type = 'table' AND name IN (
                'memory_forget_claim_rules',
                'memory_forget_evidence_events',
                'memory_correction_forget_barriers'
            )
            """).fetchone() == (0,)
        connection.execute("""
            UPDATE tom_trait_assertions
            SET updated_at = 100
            WHERE assertion_id = 'assertion-broken-time'
            """)
        connection.commit()

    command.upgrade(config, V18_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_forget_claim_rules").fetchone() == (
            1,
        )


def test_forget_governance_migration_downgrades_when_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V18_REVISION)

    command.downgrade(config, V17_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V17_REVISION,
        )
        assert connection.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type = 'table' AND name IN (
                'memory_forget_claim_rules',
                'memory_forget_evidence_events',
                'memory_correction_forget_barriers'
            )
            """).fetchone() == (0,)


def test_forget_governance_migration_refuses_to_drop_retained_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V17_REVISION)
    with sqlite3.connect(db_path) as connection:
        _insert_assertion(
            connection,
            assertion_id="assertion-retained",
            claim_fingerprint="claim-retained",
            authority_ref="forget:entity",
            raw_evidence='["event-retained"]',
            first_at=10,
            last_at=20,
            updated_at=100,
        )
        connection.commit()
    command.upgrade(config, V18_REVISION)

    with pytest.raises(RuntimeError, match="retained forget data"):
        command.downgrade(config, V17_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V18_REVISION,
        )
        assert connection.execute(
            "SELECT claim_fingerprint FROM memory_forget_claim_rules"
        ).fetchone() == ("claim-retained",)


def test_fresh_memory_schema_includes_forget_governance(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    asyncio.run(apply_memory_shared_schema(str(db_path)))

    with sqlite3.connect(db_path) as connection:
        tables = {str(row[0]) for row in connection.execute("""
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name LIKE 'memory%forget%'
                """)}
        indexes = {str(row[0]) for row in connection.execute("""
                SELECT name FROM sqlite_master
                WHERE type = 'index' AND name LIKE 'idx_memory%forget%'
                """)}
        rule_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(memory_forget_claim_rules)")
        }
        evidence_fks = {
            (str(row[3]), str(row[2]), str(row[4]), str(row[6]))
            for row in connection.execute("PRAGMA foreign_key_list(memory_forget_evidence_events)")
        }
        barrier_fks = {
            (str(row[3]), str(row[2]), str(row[4]), str(row[6]))
            for row in connection.execute(
                "PRAGMA foreign_key_list(memory_correction_forget_barriers)"
            )
        }

    assert tables == {
        "memory_forget_claim_rules",
        "memory_forget_evidence_events",
        "memory_correction_forget_barriers",
        "memory_forget_operations",
        "memory_forget_operation_events",
        "memory_forget_operation_refs",
        "memory_time_range_forget_barriers",
    }
    assert {
        "idx_memory_forget_claim_rules_lookup",
        "idx_memory_forget_evidence_event",
        "idx_memory_correction_forget_barrier_rule",
    } <= indexes
    assert rule_columns == {
        "rule_id",
        "target_kind",
        "claim_fingerprint",
        "semantic_fingerprint",
        "forget_kind",
        "effective_from",
        "effective_to",
        "evidence_fail_closed",
        "created_at",
    }
    assert evidence_fks == {
        (
            "rule_id",
            "memory_forget_claim_rules",
            "rule_id",
            "CASCADE",
        )
    }
    assert barrier_fks == {
        ("correction_id", "memory_corrections", "correction_id", "CASCADE"),
        ("rule_id", "memory_forget_claim_rules", "rule_id", "CASCADE"),
    }
