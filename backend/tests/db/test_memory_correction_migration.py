"""Regression tests for memory correction schema backfill."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import sqlite_vec
import pytest
from alembic import command

from magi.core.sqlite import sqlite_connection_async
from magi.db.migrations.memory_shared.versions.v16_relationship_correction_reconciliation import (
    reconcile_legacy_relationship_corrections,
)
from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.memory.l2.corrections.relationship_conflict_effects import (
    restore_relationship_conflict_effects,
)
from magi.memory.l2.store import L2CognitionStore


def _memory_migration_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def _insert_relationship(
    connection: sqlite3.Connection,
    *,
    triple_id: str,
    subject_id: str,
    predicate: str,
    object_id: str,
    observed_at: float,
    scope_key: str = "global",
    correction_id: str | None = None,
) -> dict[str, object]:
    connection.execute(
        """
        INSERT INTO knowledge_graph(
            triple_id, subject_id, subject_type, predicate, object_id, object_type,
            fact_kind, confidence, evidence_event_ids, observation_count,
            first_observed_at, last_observed_at, last_confirmed_at,
            source_type, extraction_method, valid_from, status, created_at,
            updated_at, evidence_class, slot_key, claim_fingerprint, authority_ref,
            scope_key, scope_json
        ) VALUES (?, ?, 'user', ?, ?, 'entity', 'explicit_fact', 0.95, '[]', 1,
                  ?, ?, ?, ?, 'explicit', ?, 'active', ?, ?, ?, ?, ?, ?, ?, '{}')
        """,
        (
            triple_id,
            subject_id,
            predicate,
            object_id,
            observed_at,
            observed_at,
            observed_at,
            "user_correction" if correction_id else "conversation",
            observed_at,
            observed_at,
            observed_at,
            "user_self_report" if correction_id else "observed_activity",
            f"slot:{subject_id}:{predicate}",
            f"claim:{triple_id}",
            f"correction:{correction_id}" if correction_id else None,
            scope_key,
        ),
    )
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT * FROM knowledge_graph WHERE triple_id = ?",
        (triple_id,),
    ).fetchone()
    assert row is not None
    return dict(row)


def _insert_legacy_relationship_correction(
    connection: sqlite3.Connection,
    *,
    correction_id: str,
    replacement: dict[str, object],
    created_at: float,
    correction_kind: str = "record_error",
    effective_at: float | None = None,
    transition_applied_at: float | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO memory_corrections(
            correction_id, request_id, actor_id, target_kind, target_id,
            slot_key, claim_fingerprint, correction_kind, before_json,
            replacement_json, effective_at, replacement_target_id, state,
            created_at, transition_applied_at
        ) VALUES (?, ?, 'user:u1', 'edge', ?, ?, ?, ?, '{}', ?, ?, ?, 'active', ?, ?)
        """,
        (
            correction_id,
            f"request:{correction_id}",
            f"original:{correction_id}",
            str(replacement["slot_key"]),
            str(replacement["claim_fingerprint"]),
            correction_kind,
            json.dumps(replacement, sort_keys=True),
            effective_at,
            str(replacement["triple_id"]),
            created_at,
            transition_applied_at,
        ),
    )


async def _restore_migrated_effects(
    db_path: Path,
    *,
    correction_id: str,
    replacement_id: str,
    now: float,
) -> None:
    async with sqlite_connection_async(str(db_path)) as db:
        await db.execute("BEGIN IMMEDIATE")
        await db.execute(
            "UPDATE knowledge_graph SET status = 'archived' WHERE triple_id = ?",
            (replacement_id,),
        )
        await restore_relationship_conflict_effects(
            db,
            correction_id=correction_id,
            replacement_id=replacement_id,
            now=now,
        )
        await db.commit()


def test_relationship_conflict_effect_migration_builds_durable_ledger(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    config = _build_config(target, db_path)
    command.upgrade(config, "v13_stable_context_scopes")
    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(memory_relationship_conflict_effects)")
        }
        indexes = {
            str(row[1])
            for row in connection.execute("PRAGMA index_list(memory_relationship_conflict_effects)")
        }

    assert {
        "effect_id",
        "correction_id",
        "victim_triple_id",
        "replacement_triple_id",
        "pre_status",
        "pre_status_reason",
        "pre_deprecated_by",
        "pre_deprecated_at",
        "pre_valid_to",
        "effective_at",
        "created_at",
        "restored_at",
    } <= columns
    assert {
        "idx_relationship_conflict_effects_correction",
        "idx_relationship_conflict_effects_victim",
        "idx_relationship_conflict_effects_replacement",
    } <= indexes


def test_relationship_reconciliation_upgrades_an_already_v14_database(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_migration_config(db_path)
    command.upgrade(config, "v14_relationship_conflict_effects")
    now = time.time()
    with sqlite3.connect(db_path) as connection:
        replacement = _insert_relationship(
            connection,
            triple_id="legacy-likes-ramen",
            subject_id="user:u1",
            predicate="LIKES",
            object_id="food:ramen",
            observed_at=now - 60,
            correction_id="legacy-like-correction",
        )
        _insert_relationship(
            connection,
            triple_id="legacy-dislikes-ramen",
            subject_id="user:u1",
            predicate="DISLIKES",
            object_id="food:ramen",
            observed_at=now - 120,
        )
        _insert_legacy_relationship_correction(
            connection,
            correction_id="legacy-like-correction",
            replacement=replacement,
            created_at=now - 60,
        )
        connection.execute(
            """
            INSERT INTO summaries(
                summary_id, summary_type, summary_category, period_start,
                period_end, content, source_event_ids, source_event_count,
                created_at, updated_at, source_revision, derivation_state
            ) VALUES ('legacy-relationship-insight', 'insight', 'identity',
                      0, ?, 'Legacy relationship insight', '[]', 0,
                      ?, ?, 0, 'current')
            """,
            (now, now - 30, now - 30),
        )
        connection.execute("""
            INSERT INTO l3_summaries_fts(summary_id, content)
            VALUES ('legacy-relationship-insight', 'Legacy relationship insight')
            """)
        connection.execute(
            """
            INSERT INTO memory_derivation_dependencies(
                artifact_kind, artifact_id, source_kind, source_id,
                subject_key, source_revision, created_at
            ) VALUES ('l3_insight', 'legacy-relationship-insight', 'edge',
                      'legacy-dislikes-ramen', 'user:u1', 0, ?)
            """,
            (now - 30,),
        )
        connection.execute(
            """
            INSERT INTO summaries(
                summary_id, summary_type, summary_category, period_start,
                period_end, content, source_event_ids, source_event_count,
                created_at, updated_at, source_revision, derivation_state
            ) VALUES ('same-subject-food-insight', 'insight', 'preference',
                      0, ?, 'Current food insight', '[]', 0,
                      ?, ?, 0, 'current')
            """,
            (now, now - 30, now - 30),
        )
        connection.execute("""
            INSERT INTO l3_summaries_fts(summary_id, content)
            VALUES ('same-subject-food-insight', 'Current food insight')
            """)
        connection.execute(
            """
            INSERT INTO memory_derivation_dependencies(
                artifact_kind, artifact_id, source_kind, source_id,
                subject_key, source_revision, created_at
            ) VALUES ('l3_insight', 'same-subject-food-insight', 'edge',
                      'unrelated-food-edge', 'food:ramen', 0, ?)
            """,
            (now - 30,),
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "v31_correction_replacement_slot_index",
        )
        assert connection.execute("""
            SELECT status, status_reason, deprecated_by
            FROM knowledge_graph
            WHERE triple_id = 'legacy-dislikes-ramen'
            """).fetchone() == (
            "deprecated",
            "user_correction_conflict:legacy-like-correction",
            "legacy-likes-ramen",
        )
        assert connection.execute("""
            SELECT correction_id, victim_triple_id, replacement_triple_id, pre_status
            FROM memory_relationship_conflict_effects
            """).fetchone() == (
            "legacy-like-correction",
            "legacy-dislikes-ramen",
            "legacy-likes-ramen",
            "active",
        )
        assert connection.execute("""
            SELECT derivation_state
            FROM summaries
            WHERE summary_id = 'legacy-relationship-insight'
            """).fetchone() == ("stale",)
        assert connection.execute("""
            SELECT COUNT(*)
            FROM l3_summaries_fts
            WHERE summary_id = 'legacy-relationship-insight'
            """).fetchone() == (0,)
        assert connection.execute("""
            SELECT COUNT(*)
            FROM l3_summaries_fts
            WHERE summary_id = 'same-subject-food-insight'
            """).fetchone() == (0,)
        assert connection.execute("""
            SELECT derivation_state
            FROM summaries
            WHERE summary_id = 'same-subject-food-insight'
            """).fetchone() == ("stale",)
        assert connection.execute("""
            SELECT revision
            FROM memory_subject_revisions
            WHERE subject_key = 'user:u1'
            """).fetchone() == (1,)
        assert connection.execute("""
            SELECT job_kind, status, target_revision
            FROM memory_derivation_jobs
            WHERE correction_id = 'legacy-like-correction'
              AND target_key = 'user:u1'
            ORDER BY job_kind
            """).fetchall() == [
            ("l3_insight", "pending", 1),
            ("portrait", "pending", 1),
            ("profile", "pending", 1),
            ("snapshot", "pending", 1),
        ]
        assert connection.execute("""
            SELECT revision
            FROM memory_subject_revisions
            WHERE subject_key = 'food:ramen'
            """).fetchone() == (1,)
        assert connection.execute("""
            SELECT job_kind, status, target_revision
            FROM memory_derivation_jobs
            WHERE correction_id = 'legacy-like-correction'
              AND target_key = 'food:ramen'
            ORDER BY job_kind
            """).fetchall() == [
            ("l3_insight", "pending", 1),
            ("snapshot", "pending", 1),
        ]


def test_relationship_reconciliation_replays_corrections_in_effective_order(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_migration_config(db_path)
    command.upgrade(config, "v14_relationship_conflict_effects")
    base_at = time.time() - 600
    with sqlite3.connect(db_path) as connection:
        _insert_relationship(
            connection,
            triple_id="residence-baseline",
            subject_id="user:u1",
            predicate="CURRENT_LIVES_IN",
            object_id="place:baseline",
            observed_at=base_at,
        )
        for index in range(1, 4):
            correction_id = f"residence-correction-{index}"
            replacement = _insert_relationship(
                connection,
                triple_id=f"residence-replacement-{index}",
                subject_id="user:u1",
                predicate="CURRENT_LIVES_IN",
                object_id=f"place:{index}",
                observed_at=base_at + 100,
                correction_id=correction_id,
            )
            _insert_legacy_relationship_correction(
                connection,
                correction_id=correction_id,
                replacement=replacement,
                created_at=base_at + 100,
            )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        effects = connection.execute("""
            SELECT correction_id, victim_triple_id, replacement_triple_id
            FROM memory_relationship_conflict_effects
            ORDER BY effective_at, correction_id
            """).fetchall()
        assert effects == [
            (
                "residence-correction-1",
                "residence-baseline",
                "residence-replacement-1",
            ),
            (
                "residence-correction-2",
                "residence-replacement-1",
                "residence-replacement-2",
            ),
            (
                "residence-correction-3",
                "residence-replacement-2",
                "residence-replacement-3",
            ),
        ]
        assert connection.execute("""
            SELECT triple_id, status, deprecated_by
            FROM knowledge_graph
            WHERE triple_id LIKE 'residence-%'
            ORDER BY triple_id
            """).fetchall() == [
            ("residence-baseline", "deprecated", "residence-replacement-1"),
            (
                "residence-replacement-1",
                "deprecated",
                "residence-replacement-2",
            ),
            (
                "residence-replacement-2",
                "deprecated",
                "residence-replacement-3",
            ),
            ("residence-replacement-3", "active", None),
        ]

    asyncio.run(
        _restore_migrated_effects(
            db_path,
            correction_id="residence-correction-3",
            replacement_id="residence-replacement-3",
            now=base_at + 1000,
        )
    )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT triple_id, status, deprecated_by
            FROM knowledge_graph
            WHERE triple_id IN ('residence-baseline', 'residence-replacement-1',
                                'residence-replacement-2')
            ORDER BY triple_id
            """).fetchall() == [
            ("residence-baseline", "deprecated", "residence-replacement-1"),
            (
                "residence-replacement-1",
                "deprecated",
                "residence-replacement-2",
            ),
            ("residence-replacement-2", "active", None),
        ]

    asyncio.run(
        _restore_migrated_effects(
            db_path,
            correction_id="residence-correction-2",
            replacement_id="residence-replacement-2",
            now=base_at + 1100,
        )
    )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT triple_id, status, deprecated_by
            FROM knowledge_graph
            WHERE triple_id IN ('residence-baseline', 'residence-replacement-1')
            ORDER BY triple_id
            """).fetchall() == [
            ("residence-baseline", "deprecated", "residence-replacement-1"),
            ("residence-replacement-1", "active", None),
        ]

    asyncio.run(
        _restore_migrated_effects(
            db_path,
            correction_id="residence-correction-1",
            replacement_id="residence-replacement-1",
            now=base_at + 1200,
        )
    )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT status, deprecated_by
            FROM knowledge_graph
            WHERE triple_id = 'residence-baseline'
            """).fetchone() == ("active", None)


def test_relationship_reconciliation_repairs_mixed_legacy_and_runtime_effects(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_migration_config(db_path)
    command.upgrade(config, "v14_relationship_conflict_effects")
    base_at = time.time() - 600
    with sqlite3.connect(db_path) as connection:
        baseline = _insert_relationship(
            connection,
            triple_id="mixed-residence-baseline",
            subject_id="user:u1",
            predicate="CURRENT_LIVES_IN",
            object_id="place:baseline",
            observed_at=base_at,
        )
        first = _insert_relationship(
            connection,
            triple_id="mixed-residence-first",
            subject_id="user:u1",
            predicate="CURRENT_LIVES_IN",
            object_id="place:first",
            observed_at=base_at + 100,
            correction_id="mixed-correction-first",
        )
        second = _insert_relationship(
            connection,
            triple_id="mixed-residence-second",
            subject_id="user:u1",
            predicate="CURRENT_LIVES_IN",
            object_id="place:second",
            observed_at=base_at + 200,
            correction_id="mixed-correction-second",
        )
        _insert_legacy_relationship_correction(
            connection,
            correction_id="mixed-correction-first",
            replacement=first,
            created_at=base_at + 100,
        )
        _insert_legacy_relationship_correction(
            connection,
            correction_id="mixed-correction-second",
            replacement=second,
            created_at=base_at + 200,
        )
        for victim in (baseline, first):
            connection.execute(
                """
                INSERT INTO memory_relationship_conflict_effects(
                    effect_id, correction_id, victim_triple_id,
                    replacement_triple_id, pre_status, pre_status_reason,
                    pre_deprecated_by, pre_deprecated_at, pre_valid_to,
                    effective_at, created_at, restored_at
                ) VALUES (?, 'mixed-correction-second', ?,
                          'mixed-residence-second', 'active', NULL, NULL, NULL,
                          NULL, ?, ?, NULL)
                """,
                (
                    f"runtime-effect:{victim['triple_id']}",
                    str(victim["triple_id"]),
                    base_at + 200,
                    base_at + 200,
                ),
            )
            connection.execute(
                """
                UPDATE knowledge_graph
                SET status = 'deprecated',
                    status_reason = 'user_correction_conflict:mixed-correction-second',
                    deprecated_by = 'mixed-residence-second',
                    deprecated_at = ?, valid_to = ?
                WHERE triple_id = ?
                """,
                (
                    base_at + 200,
                    base_at + 200,
                    str(victim["triple_id"]),
                ),
            )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT correction_id, victim_triple_id, replacement_triple_id
            FROM memory_relationship_conflict_effects
            ORDER BY correction_id, victim_triple_id
            """).fetchall() == [
            (
                "mixed-correction-first",
                "mixed-residence-baseline",
                "mixed-residence-first",
            ),
            (
                "mixed-correction-second",
                "mixed-residence-first",
                "mixed-residence-second",
            ),
        ]
        assert connection.execute("""
            SELECT triple_id, status, deprecated_by
            FROM knowledge_graph
            WHERE triple_id LIKE 'mixed-residence-%'
            ORDER BY triple_id
            """).fetchall() == [
            ("mixed-residence-baseline", "deprecated", "mixed-residence-first"),
            ("mixed-residence-first", "deprecated", "mixed-residence-second"),
            ("mixed-residence-second", "active", None),
        ]

    asyncio.run(
        _restore_migrated_effects(
            db_path,
            correction_id="mixed-correction-second",
            replacement_id="mixed-residence-second",
            now=base_at + 1000,
        )
    )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT triple_id, status, deprecated_by
            FROM knowledge_graph
            WHERE triple_id IN ('mixed-residence-baseline', 'mixed-residence-first')
            ORDER BY triple_id
            """).fetchall() == [
            ("mixed-residence-baseline", "deprecated", "mixed-residence-first"),
            ("mixed-residence-first", "active", None),
        ]


def test_relationship_reconciliation_preserves_later_runtime_effects(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_migration_config(db_path)
    command.upgrade(config, "v14_relationship_conflict_effects")
    base_at = time.time() - 600
    with sqlite3.connect(db_path) as connection:
        baseline = _insert_relationship(
            connection,
            triple_id="preserved-residence-baseline",
            subject_id="user:u1",
            predicate="CURRENT_LIVES_IN",
            object_id="place:baseline",
            observed_at=base_at,
        )
        replacement = _insert_relationship(
            connection,
            triple_id="preserved-residence-replacement",
            subject_id="user:u1",
            predicate="CURRENT_LIVES_IN",
            object_id="place:replacement",
            observed_at=base_at + 100,
            correction_id="preserved-residence-correction",
        )
        later = _insert_relationship(
            connection,
            triple_id="preserved-residence-later",
            subject_id="user:u1",
            predicate="CURRENT_LIVES_IN",
            object_id="place:later",
            observed_at=base_at + 200,
        )
        _insert_legacy_relationship_correction(
            connection,
            correction_id="preserved-residence-correction",
            replacement=replacement,
            created_at=base_at + 100,
        )
        for effect_id, victim, created_at in (
            ("runtime-baseline-effect", baseline, base_at + 100),
            ("runtime-later-effect", later, base_at + 200),
        ):
            connection.execute(
                """
                INSERT INTO memory_relationship_conflict_effects(
                    effect_id, correction_id, victim_triple_id,
                    replacement_triple_id, pre_status, pre_status_reason,
                    pre_deprecated_by, pre_deprecated_at, pre_valid_to,
                    effective_at, created_at, restored_at
                ) VALUES (?, 'preserved-residence-correction', ?,
                          'preserved-residence-replacement', 'active', NULL,
                          NULL, NULL, NULL, ?, ?, NULL)
                """,
                (
                    effect_id,
                    str(victim["triple_id"]),
                    base_at + 100,
                    created_at,
                ),
            )
            connection.execute(
                """
                UPDATE knowledge_graph
                SET status = 'deprecated',
                    status_reason =
                        'user_correction_conflict:preserved-residence-correction',
                    deprecated_by = 'preserved-residence-replacement',
                    deprecated_at = ?, valid_to = ?
                WHERE triple_id = ?
                """,
                (base_at + 100, base_at + 100, str(victim["triple_id"])),
            )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        effects = connection.execute("""
            SELECT effect_id, victim_triple_id
            FROM memory_relationship_conflict_effects
            ORDER BY victim_triple_id
            """).fetchall()
        assert effects[0][0].startswith("relationship_conflict_effect_reconciled_")
        assert effects == [
            (effects[0][0], "preserved-residence-baseline"),
            ("runtime-later-effect", "preserved-residence-later"),
        ]
        assert connection.execute("""
            SELECT triple_id, status, deprecated_by
            FROM knowledge_graph
            WHERE triple_id IN (
                'preserved-residence-baseline', 'preserved-residence-later'
            )
            ORDER BY triple_id
            """).fetchall() == [
            (
                "preserved-residence-baseline",
                "deprecated",
                "preserved-residence-replacement",
            ),
            (
                "preserved-residence-later",
                "deprecated",
                "preserved-residence-replacement",
            ),
        ]

    asyncio.run(
        _restore_migrated_effects(
            db_path,
            correction_id="preserved-residence-correction",
            replacement_id="preserved-residence-replacement",
            now=base_at + 1000,
        )
    )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT triple_id, status, deprecated_by
            FROM knowledge_graph
            WHERE triple_id IN (
                'preserved-residence-baseline', 'preserved-residence-later'
            )
            ORDER BY triple_id
            """).fetchall() == [
            ("preserved-residence-baseline", "active", None),
            ("preserved-residence-later", "active", None),
        ]


def test_relationship_reconciliation_defers_pending_future_corrections(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_migration_config(db_path)
    command.upgrade(config, "v14_relationship_conflict_effects")
    now = time.time()
    effective_at = now + 600
    with sqlite3.connect(db_path) as connection:
        _insert_relationship(
            connection,
            triple_id="future-dislikes-ramen",
            subject_id="user:u1",
            predicate="DISLIKES",
            object_id="food:ramen",
            observed_at=now - 120,
        )
        replacement = _insert_relationship(
            connection,
            triple_id="future-likes-ramen",
            subject_id="user:u1",
            predicate="LIKES",
            object_id="food:ramen",
            observed_at=effective_at,
            correction_id="future-like-correction",
        )
        _insert_legacy_relationship_correction(
            connection,
            correction_id="future-like-correction",
            replacement=replacement,
            correction_kind="situation_changed",
            effective_at=effective_at,
            transition_applied_at=None,
            created_at=now,
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT status, deprecated_by
            FROM knowledge_graph
            WHERE triple_id = 'future-dislikes-ramen'
            """).fetchone() == ("active", None)
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_relationship_conflict_effects"
        ).fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM memory_subject_revisions").fetchone() == (
            0,
        )
        assert connection.execute("SELECT COUNT(*) FROM memory_derivation_jobs").fetchone() == (0,)

    store = L2CognitionStore(db_path=str(db_path))
    with patch("time.time", return_value=effective_at + 1):
        processed = asyncio.run(store.process_memory_correction_jobs(limit=10))
    assert processed["activated"] == 1
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT status, deprecated_by
            FROM knowledge_graph
            WHERE triple_id = 'future-dislikes-ramen'
            """).fetchone() == ("deprecated", "future-likes-ramen")
        assert connection.execute(
            "SELECT correction_id FROM memory_relationship_conflict_effects"
        ).fetchone() == ("future-like-correction",)
        assert connection.execute(
            "SELECT revision FROM memory_subject_revisions WHERE subject_key = 'user:u1'"
        ).fetchone() == (1,)


def test_relationship_reconciliation_uses_persisted_custom_rules_and_scope(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_migration_config(db_path)
    command.upgrade(config, "v14_relationship_conflict_effects")
    now = time.time()
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO graph_conflict_rules(
                predicate, opposite_predicates, opposite_resolution,
                exclusive_group, exclusive_scope, exclusive_resolution,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'same_subject', ?, ?, ?)
            """,
            [
                (
                    "PREFERS",
                    '["AVOIDS"]',
                    "mark_conflicted",
                    None,
                    "mark_deprecated",
                    now,
                    now,
                ),
                (
                    "CURRENT_FOCUS",
                    "[]",
                    "mark_deprecated",
                    "focus",
                    "mark_deprecated",
                    now,
                    now,
                ),
                (
                    "PRIMARY_FOCUS",
                    "[]",
                    "mark_deprecated",
                    "focus",
                    "mark_deprecated",
                    now,
                    now,
                ),
            ],
        )
        _insert_relationship(
            connection,
            triple_id="custom-avoids-global",
            subject_id="user:u1",
            predicate="AVOIDS",
            object_id="food:ramen",
            observed_at=now - 120,
        )
        _insert_relationship(
            connection,
            triple_id="custom-avoids-other-scope",
            subject_id="user:u1",
            predicate="AVOIDS",
            object_id="food:ramen",
            observed_at=now - 120,
            scope_key="scope:other",
        )
        prefers = _insert_relationship(
            connection,
            triple_id="custom-prefers-global",
            subject_id="user:u1",
            predicate="PREFERS",
            object_id="food:ramen",
            observed_at=now - 60,
            correction_id="custom-prefers-correction",
        )
        _insert_legacy_relationship_correction(
            connection,
            correction_id="custom-prefers-correction",
            replacement=prefers,
            created_at=now - 60,
        )
        _insert_relationship(
            connection,
            triple_id="custom-primary-focus",
            subject_id="user:u2",
            predicate="PRIMARY_FOCUS",
            object_id="topic:one",
            observed_at=now - 120,
        )
        focus = _insert_relationship(
            connection,
            triple_id="custom-current-focus",
            subject_id="user:u2",
            predicate="CURRENT_FOCUS",
            object_id="topic:two",
            observed_at=now - 60,
            correction_id="custom-focus-correction",
        )
        _insert_legacy_relationship_correction(
            connection,
            correction_id="custom-focus-correction",
            replacement=focus,
            created_at=now - 60,
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT triple_id, status, deprecated_by
            FROM knowledge_graph
            WHERE triple_id IN (
                'custom-avoids-global', 'custom-avoids-other-scope',
                'custom-primary-focus'
            )
            ORDER BY triple_id
            """).fetchall() == [
            ("custom-avoids-global", "conflicted", "custom-prefers-global"),
            ("custom-avoids-other-scope", "active", None),
            ("custom-primary-focus", "deprecated", "custom-current-focus"),
        ]
        assert connection.execute("""
            SELECT correction_id, victim_triple_id
            FROM memory_relationship_conflict_effects
            ORDER BY correction_id
            """).fetchall() == [
            ("custom-focus-correction", "custom-primary-focus"),
            ("custom-prefers-correction", "custom-avoids-global"),
        ]


def test_relationship_reconciliation_is_idempotent_and_retryable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_migration_config(db_path)
    command.upgrade(config, "v15_correction_evidence_fail_closed")
    now = time.time()
    with sqlite3.connect(db_path) as connection:
        replacement = _insert_relationship(
            connection,
            triple_id="retry-likes-ramen",
            subject_id="user:u1",
            predicate="LIKES",
            object_id="food:ramen",
            observed_at=now - 60,
            correction_id="retry-like-correction",
        )
        _insert_relationship(
            connection,
            triple_id="retry-dislikes-ramen",
            subject_id="user:u1",
            predicate="DISLIKES",
            object_id="food:ramen",
            observed_at=now - 120,
        )
        _insert_legacy_relationship_correction(
            connection,
            correction_id="retry-like-correction",
            replacement=replacement,
            created_at=now - 60,
        )
        connection.execute("""
            CREATE TRIGGER fail_relationship_reconciliation_version
            BEFORE INSERT ON knowledge_graph_versions
            WHEN NEW.correction_id = 'retry-like-correction'
            BEGIN
                SELECT RAISE(ABORT, 'forced relationship reconciliation failure');
            END
            """)
        connection.commit()

    with pytest.raises(Exception, match="forced relationship reconciliation failure"):
        command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "v15_correction_evidence_fail_closed",
        )
        assert connection.execute(
            "SELECT status FROM knowledge_graph WHERE triple_id = 'retry-dislikes-ramen'"
        ).fetchone() == ("active",)
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_relationship_conflict_effects"
        ).fetchone() == (0,)
        assert connection.execute("""
            SELECT COUNT(*) FROM knowledge_graph_versions
            WHERE correction_id = 'retry-like-correction'
            """).fetchone() == (0,)
        connection.execute("DROP TRIGGER fail_relationship_reconciliation_version")
        connection.commit()

    command.upgrade(config, "head")
    with sqlite3.connect(db_path) as connection:
        before = (
            connection.execute(
                "SELECT COUNT(*) FROM memory_relationship_conflict_effects"
            ).fetchone()[0],
            connection.execute("""
                SELECT COUNT(*) FROM knowledge_graph_versions
                WHERE correction_id = 'retry-like-correction'
                """).fetchone()[0],
        )
        reconcile_legacy_relationship_corrections(connection, now=now + 1000)
        reconcile_legacy_relationship_corrections(connection, now=now + 2000)
        connection.commit()
        after = (
            connection.execute(
                "SELECT COUNT(*) FROM memory_relationship_conflict_effects"
            ).fetchone()[0],
            connection.execute("""
                SELECT COUNT(*) FROM knowledge_graph_versions
                WHERE correction_id = 'retry-like-correction'
                """).fetchone()[0],
        )
    assert before == after == (1, 2)


def test_relationship_reconciliation_rejects_destructive_downgrade(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_migration_config(db_path)
    command.upgrade(config, "v14_relationship_conflict_effects")
    now = time.time()
    with sqlite3.connect(db_path) as connection:
        replacement = _insert_relationship(
            connection,
            triple_id="downgrade-likes-ramen",
            subject_id="user:u1",
            predicate="LIKES",
            object_id="food:ramen",
            observed_at=now - 60,
            correction_id="downgrade-like-correction",
        )
        _insert_relationship(
            connection,
            triple_id="downgrade-dislikes-ramen",
            subject_id="user:u1",
            predicate="DISLIKES",
            object_id="food:ramen",
            observed_at=now - 120,
        )
        _insert_legacy_relationship_correction(
            connection,
            correction_id="downgrade-like-correction",
            replacement=replacement,
            created_at=now - 60,
        )
        connection.commit()
    command.upgrade(config, "head")
    command.downgrade(config, "v16_relationship_correction_reconciliation")

    with pytest.raises(
        RuntimeError,
        match="Relationship correction reconciliation cannot be downgraded safely",
    ):
        command.downgrade(config, "v15_correction_evidence_fail_closed")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "v16_relationship_correction_reconciliation",
        )
        assert connection.execute("""
            SELECT status, deprecated_by
            FROM knowledge_graph
            WHERE triple_id = 'downgrade-dislikes-ramen'
            """).fetchone() == ("deprecated", "downgrade-likes-ramen")
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_relationship_conflict_effects"
        ).fetchone() == (1,)


def test_scheduled_transition_migration_marks_only_due_changes_applied(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    config = _build_config(target, db_path)
    command.upgrade(config, "v11_correction_evidence_governance")
    now = time.time()

    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                replacement_json, effective_at, replacement_target_id, state,
                created_at
            ) VALUES (?, ?, 'user:u1', 'assertion', ?, 'slot-home', ?,
                      'situation_changed', ?, ?, ?, ?, 'active', ?)
            """,
            [
                (
                    "correction-past",
                    "request-past",
                    "assertion-old-past",
                    "claim-old-past",
                    '{"entity_id":"user:u1","trait_value":"Past original"}',
                    '{"value":"Past replacement"}',
                    now - 60,
                    "assertion-new-past",
                    now - 120,
                ),
                (
                    "correction-future",
                    "request-future",
                    "assertion-old-future",
                    "claim-old-future",
                    '{"entity_id":"user:u1","trait_value":"Future original"}',
                    '{"value":"Future replacement"}',
                    now + 600,
                    "assertion-new-future",
                    now,
                ),
            ],
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(memory_corrections)")
        }
        indexes = {
            str(row[1]) for row in connection.execute("PRAGMA index_list(memory_corrections)")
        }
        markers = dict(
            connection.execute("""
            SELECT correction_id, transition_applied_at
            FROM memory_corrections
            ORDER BY correction_id
            """).fetchall()
        )

    assert "transition_applied_at" in columns
    assert "idx_memory_corrections_due_transition" in indexes
    assert markers["correction-future"] is None
    assert markers["correction-past"] == pytest.approx(now - 120)


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
        correction_evidence = connection.execute("""
            SELECT target_kind, event_id
            FROM memory_correction_evidence_events
            ORDER BY target_kind
            """).fetchall()
        assert correction_evidence == [
            ("assertion", "event-1"),
            ("edge", "event-1"),
        ]
        edge_governance = connection.execute("""
            SELECT corrections.slot_key, corrections.claim_fingerprint,
                   rules.slot_key, rules.claim_fingerprint,
                   versions.slot_key, versions.claim_fingerprint
            FROM memory_corrections AS corrections
            JOIN memory_correction_rules AS rules
              ON rules.correction_id = corrections.correction_id
            JOIN knowledge_graph_versions AS versions
              ON versions.triple_id = corrections.target_id
            WHERE corrections.target_kind = 'edge'
            """).fetchone()
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
        connection.execute("""
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
            """)
        connection.execute("""
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
            """)
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT governance_complete, evidence_class, expires_at
            FROM knowledge_graph_versions
            WHERE version_id = 'version-legacy'
            """).fetchone() == (0, None, None)

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
    assert asyncio.run(store.active_correction_evidence_event_ids(["event-1"])) == {"event-1"}
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
    assert [item["triple_id"] for item in historical_after_new_write] == ["triple-legacy"]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("""
            SELECT COUNT(*) FROM knowledge_graph_versions
            WHERE triple_id = 'triple-legacy' AND governance_complete = 1
            """).fetchone() == (2,)


def test_correction_evidence_migration_fails_closed_on_malformed_json(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    config = _build_config(target, db_path)
    command.upgrade(config, "v10_relationship_version_snapshot")

    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                state, created_at
            ) VALUES (
                'correction-invalid-evidence', 'request-invalid-evidence',
                'user:u1', 'assertion', 'assert-invalid', 'slot-invalid',
                'claim-invalid', 'record_error',
                '{"trait_value":"Old value","evidence_events":"[broken"}',
                'active', 100
            )
            """)
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
                    '{"trait_value":"Old value","evidence_events":{"event_id":"candidate-object"}}',
                ),
                (
                    "correction-number-evidence",
                    "request-number-evidence",
                    "assert-number",
                    "slot-number",
                    "claim-number",
                    '{"trait_value":"Old value","evidence_events":123}',
                ),
                (
                    "correction-array-object-evidence",
                    "request-array-object-evidence",
                    "assert-array-object",
                    "slot-array-object",
                    "claim-array-object",
                    '{"trait_value":"Old value","evidence_events":["candidate-valid",{"event_id":"candidate-bad"}]}',
                ),
                (
                    "correction-literal-star-evidence",
                    "request-literal-star-evidence",
                    "assert-literal-star",
                    "slot-literal-star",
                    "claim-literal-star",
                    '{"trait_value":"Old value","evidence_events":["*"]}',
                ),
            ],
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        fail_closed = connection.execute("""
            SELECT correction_id
            FROM memory_correction_evidence_fail_closed
            ORDER BY correction_id
            """).fetchall()
        assert fail_closed == [
            ("correction-array-object-evidence",),
            ("correction-invalid-evidence",),
            ("correction-number-evidence",),
            ("correction-object-evidence",),
        ]
        literal_star_events = connection.execute("""
            SELECT correction_id
            FROM memory_correction_evidence_events
            WHERE event_id = '*'
            ORDER BY correction_id
            """).fetchall()
        assert literal_star_events == [("correction-literal-star-evidence",)]
    store = L2CognitionStore(db_path=str(db_path))
    assert asyncio.run(
        store.active_correction_evidence_event_ids(["candidate-a", "candidate-b"])
    ) == {"candidate-a", "candidate-b"}

    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            UPDATE memory_corrections
            SET state = 'reverted', reverted_at = 200
            WHERE correction_id IN (
                'correction-array-object-evidence',
                'correction-invalid-evidence',
                'correction-number-evidence',
                'correction-object-evidence'
            )
            """)
        connection.commit()
    assert asyncio.run(
        store.active_correction_evidence_event_ids(["*", "candidate-unrelated"])
    ) == {"*"}


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
        connection.execute("""
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
            """)
        connection.execute("""
            INSERT INTO memory_derivation_dependencies(
                artifact_kind, artifact_id, source_kind, source_id,
                subject_key, source_revision, created_at
            ) VALUES ('l3_insight', 'legacy-linked', 'assertion', 'assertion-1',
                      'user:local_user', 0, 2)
            """)
        connection.execute("""
            INSERT INTO memory_derivation_dependencies(
                artifact_kind, artifact_id, source_kind, source_id,
                subject_key, source_revision, created_at
            ) VALUES ('l3_insight', 'legacy-orphan', 'assertion', 'missing-assertion',
                      'user:local_user', 0, 2)
            """)
        connection.execute("""
            INSERT INTO l3_summary_chunks(
                chunk_id, summary_id, chunk_index, chunk_text,
                char_start, char_end, token_estimate, created_at, updated_at
            ) VALUES ('chunk-legacy', 'legacy-unknown', 0, 'legacy', 0, 6, 1, 1, 2)
            """)
        connection.enable_load_extension(True)
        try:
            connection.load_extension(sqlite_vec.loadable_path())
        finally:
            connection.enable_load_extension(False)
        connection.execute("""
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
            """)
        connection.execute(
            "CREATE VIRTUAL TABLE l3_summary_chunk_vec_test USING vec0(embedding float[2])"
        )
        connection.execute(
            "INSERT INTO l3_summary_chunk_vec_test(rowid, embedding) VALUES (1, ?)",
            (sqlite_vec.serialize_float32([1.0, 0.0]),),
        )
        connection.execute("""
            INSERT INTO l3_summary_chunk_vectors(
                vec_rowid, chunk_id, embedding_model, embedding_dim, vec_table,
                metadata, created_at, updated_at
            ) VALUES (1, 'chunk-legacy', 'test', 2, 'l3_summary_chunk_vec_test', NULL, 1, 2)
            """)
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
        assert connection.execute("""
            SELECT embedding_status, embedding_profile_id,
                   embedding_chunk_count, last_embedded_at
            FROM summaries WHERE summary_id = 'legacy-unknown'
            """).fetchone() == ("disabled", None, 0, None)
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
        assert connection.execute("SELECT COUNT(*) FROM l3_summary_chunk_vec_test").fetchone() == (
            0,
        )
