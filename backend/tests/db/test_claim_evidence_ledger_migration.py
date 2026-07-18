"""Regression coverage for the claim evidence ledger migration."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command

from _shared.memory_schema import apply_memory_shared_schema
from magi.db.runner import MIGRATION_TARGETS, _build_config

V18_REVISION = "v18_persistent_forget_governance"
V19_REVISION = "v19_claim_evidence_ledger"


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def _insert_assertion(
    connection: sqlite3.Connection,
    *,
    assertion_id: str,
    claim_fingerprint: str,
    raw_evidence: str,
    observed_at: float | str,
    created_at: float,
) -> None:
    connection.execute(
        """
        INSERT INTO tom_trait_assertions(
            assertion_id, entity_id, entity_type, trait_family, trait_name,
            trait_value, confidence_score, evidence_events, volatility_index,
            source_domain, inference_depth, validation_state, first_inferred_at,
            last_validated_at, target_entity_id, target_entity_type, target_scope,
            temporal_scope, status, natural_summary, created_at, updated_at,
            slot_key, claim_fingerprint, version_root_id, valid_from,
            scope_key, scope_json
        ) VALUES (?, ?, 'entity', 'preference', ?, ?, 0.9, ?, 0.1,
                  'chat', 'explicit', 'stable', ?, ?, '', '', 'global',
                  'stable', 'archived', '', ?, ?, ?, ?, ?, ?, 'global', '{}')
        """,
        (
            assertion_id,
            f"entity:{assertion_id}",
            f"trait:{assertion_id}",
            f"value:{assertion_id}",
            raw_evidence,
            created_at,
            observed_at,
            created_at,
            observed_at,
            f"slot:{assertion_id}",
            claim_fingerprint,
            assertion_id,
            created_at,
        ),
    )


def _insert_edge(
    connection: sqlite3.Connection,
    *,
    triple_id: str,
    claim_fingerprint: str,
    raw_evidence: str,
    observed_at: float | str,
    created_at: float,
) -> None:
    connection.execute(
        """
        INSERT INTO knowledge_graph(
            triple_id, subject_id, subject_type, predicate, object_id, object_type,
            fact_kind, confidence, evidence_event_ids, observation_count,
            first_observed_at, last_observed_at, source_type, extraction_method,
            valid_from, status, created_at, updated_at, evidence_class,
            slot_key, claim_fingerprint, scope_key, scope_json
        ) VALUES (?, 'user:u1', 'user', ?, ?, 'entity', 'explicit_fact',
                  0.9, ?, 1, ?, ?, 'conversation', 'explicit', ?, 'archived',
                  ?, ?, 'user_self_report', ?, ?, 'global', '{}')
        """,
        (
            triple_id,
            f"REL_{triple_id.upper().replace('-', '_')}",
            f"object:{triple_id}",
            raw_evidence,
            created_at,
            observed_at,
            created_at,
            created_at,
            observed_at,
            f"slot:{triple_id}",
            claim_fingerprint,
        ),
    )


def _insert_edge_version(
    connection: sqlite3.Connection,
    *,
    version_id: str,
    triple_id: str,
    claim_fingerprint: str,
    raw_evidence: str,
    observed_at: float | None,
    edge_created_at: float | None,
    recorded_at: float,
    governance_complete: int = 1,
) -> None:
    connection.execute(
        """
        INSERT INTO knowledge_graph_versions(
            version_id, triple_id, slot_key, claim_fingerprint,
            subject_id, subject_type, predicate, object_id, object_type,
            fact_kind, confidence, evidence_event_ids, status, created_at,
            last_observed_at, edge_created_at, governance_complete
        ) VALUES (?, ?, ?, ?, 'user:u1', 'user', ?, ?, 'entity',
                  'explicit_fact', 0.9, ?, 'active', ?, ?, ?, ?)
        """,
        (
            version_id,
            triple_id,
            f"slot:{triple_id}",
            claim_fingerprint,
            f"REL_{triple_id.upper().replace('-', '_')}",
            f"object:{triple_id}",
            raw_evidence,
            recorded_at,
            observed_at,
            edge_created_at,
            governance_complete,
        ),
    )


def test_claim_evidence_ledger_backfills_valid_arrays_and_skips_malformed(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V18_REVISION)

    with sqlite3.connect(db_path) as connection:
        _insert_assertion(
            connection,
            assertion_id="assertion-primary",
            claim_fingerprint="claim-a",
            raw_evidence=json.dumps(["event-shared", "*", "event-assertion"]),
            observed_at=20,
            created_at=10,
        )
        _insert_assertion(
            connection,
            assertion_id="assertion-duplicate",
            claim_fingerprint="claim-a",
            raw_evidence=json.dumps(["event-shared", "event-shared"]),
            observed_at=35,
            created_at=5,
        )
        _insert_edge(
            connection,
            triple_id="edge-primary",
            claim_fingerprint="claim-b",
            raw_evidence=json.dumps(json.dumps(["event-edge"])),
            observed_at=80,
            created_at=60,
        )
        _insert_edge(
            connection,
            triple_id="edge-same-claim",
            claim_fingerprint="claim-a",
            raw_evidence=json.dumps(["event-shared"]),
            observed_at=90,
            created_at=70,
        )
        _insert_edge_version(
            connection,
            version_id="version-edge-primary",
            triple_id="edge-primary",
            claim_fingerprint="claim-b",
            raw_evidence=json.dumps(["event-edge", "event-edge-history"]),
            observed_at=40,
            edge_created_at=15,
            recorded_at=50,
        )
        _insert_edge_version(
            connection,
            version_id="version-only-legacy",
            triple_id="edge-version-only",
            claim_fingerprint="claim-version-only",
            raw_evidence='["event-version-only"]',
            observed_at=None,
            edge_created_at=None,
            recorded_at=45,
            governance_complete=0,
        )
        _insert_edge_version(
            connection,
            version_id="version-malformed",
            triple_id="edge-version-malformed",
            claim_fingerprint="claim-version-malformed",
            raw_evidence='["event-version-malformed", 7]',
            observed_at=None,
            edge_created_at=None,
            recorded_at=47,
        )
        for assertion_id, raw_evidence in (
            ("assertion-broken-json", "[broken"),
            ("assertion-object", '{"event_id":"event-object"}'),
            ("assertion-mixed", '["event-mixed",7]'),
            ("assertion-blank", '[""]'),
        ):
            _insert_assertion(
                connection,
                assertion_id=assertion_id,
                claim_fingerprint=f"claim-{assertion_id}",
                raw_evidence=raw_evidence,
                observed_at=100,
                created_at=95,
            )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "v31_correction_replacement_slot_index",
        )
        rows = connection.execute("""
            SELECT target_kind, claim_fingerprint, event_id,
                   observed_at, observed_from, observed_to,
                   observed_at_is_approximate, created_at
            FROM memory_claim_evidence_events
            ORDER BY target_kind, claim_fingerprint, event_id
            """).fetchall()

    assert rows == [
        ("assertion", "claim-a", "*", 20.0, 10.0, 20.0, 1, 10.0),
        ("assertion", "claim-a", "event-assertion", 20.0, 10.0, 20.0, 1, 10.0),
        ("assertion", "claim-a", "event-shared", 20.0, 5.0, 35.0, 1, 5.0),
        ("edge", "claim-a", "event-shared", 90.0, 70.0, 90.0, 1, 70.0),
        ("edge", "claim-b", "event-edge", 40.0, 15.0, 80.0, 1, 15.0),
        ("edge", "claim-b", "event-edge-history", 40.0, 15.0, 40.0, 1, 15.0),
        ("edge", "claim-version-only", "event-version-only", 45.0, 45.0, 45.0, 1, 45.0),
    ]


def test_claim_evidence_ledger_upgrade_rolls_back_and_retries(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, V18_REVISION)
    with sqlite3.connect(db_path) as connection:
        _insert_assertion(
            connection,
            assertion_id="assertion-invalid-time",
            claim_fingerprint="claim-invalid-time",
            raw_evidence='["event-invalid-time"]',
            observed_at="not-a-time",
            created_at=10,
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="Invalid observed_at"):
        command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V18_REVISION,
        )
        assert connection.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type = 'table' AND name = 'memory_claim_evidence_events'
            """).fetchone() == (0,)
        connection.execute("""
            UPDATE tom_trait_assertions
            SET last_validated_at = 20
            WHERE assertion_id = 'assertion-invalid-time'
            """)
        connection.commit()

    command.upgrade(config, "head")
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT event_id, observed_at FROM memory_claim_evidence_events"
        ).fetchone() == ("event-invalid-time", 20.0)


def test_claim_evidence_ledger_downgrades_when_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, "head")

    command.downgrade(config, V18_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V18_REVISION,
        )
        assert connection.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type IN ('table', 'index')
              AND name IN (
                  'memory_claim_evidence_events',
                  'idx_memory_claim_evidence_claim_observed',
                  'idx_memory_claim_evidence_event',
                  'idx_memory_claim_evidence_approximate_event'
              )
            """).fetchone() == (0,)


def test_claim_evidence_ledger_refuses_to_drop_retained_data(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, "head")
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            INSERT INTO memory_claim_evidence_events(
                target_kind, claim_fingerprint, event_id,
                observed_at, observed_from, observed_to, created_at
            ) VALUES (
                'assertion', 'claim-retained', 'event-retained',
                20, 10, 20, 10
            )
            """)
        connection.commit()

    with pytest.raises(RuntimeError, match="retained evidence data"):
        command.downgrade(config, V18_REVISION)

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            V19_REVISION,
        )
        assert connection.execute("""
            SELECT claim_fingerprint, observed_at_is_approximate
            FROM memory_claim_evidence_events
            """).fetchone() == ("claim-retained", 1)


def test_fresh_memory_schema_includes_claim_evidence_ledger(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    asyncio.run(apply_memory_shared_schema(str(db_path)))

    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1]): (
                str(row[2]),
                int(row[3]),
                int(row[5]),
                None if row[4] is None else str(row[4]),
            )
            for row in connection.execute("PRAGMA table_info(memory_claim_evidence_events)")
        }
        indexes = {
            str(row[1])
            for row in connection.execute("PRAGMA index_list(memory_claim_evidence_events)")
        }
        approximate_refresh_plan = " ".join(
            str(row[3])
            for row in connection.execute(
                """
                EXPLAIN QUERY PLAN
                SELECT DISTINCT event_id
                FROM memory_claim_evidence_events
                WHERE observed_at_is_approximate = 1 AND event_id > ?
                ORDER BY event_id
                LIMIT 500
                """,
                ("",),
            )
        )

    assert columns == {
        "target_kind": ("TEXT", 1, 1, None),
        "claim_fingerprint": ("TEXT", 1, 2, None),
        "event_id": ("TEXT", 1, 3, None),
        "observed_at": ("REAL", 1, 0, None),
        "observed_from": ("REAL", 1, 0, None),
        "observed_to": ("REAL", 1, 0, None),
        "observed_at_is_approximate": ("INTEGER", 1, 0, "1"),
        "created_at": ("REAL", 1, 0, None),
    }
    assert {
        "idx_memory_claim_evidence_claim_observed",
        "idx_memory_claim_evidence_event",
        "idx_memory_claim_evidence_approximate_event",
    } <= indexes
    assert "idx_memory_claim_evidence_approximate_event" in approximate_refresh_plan
