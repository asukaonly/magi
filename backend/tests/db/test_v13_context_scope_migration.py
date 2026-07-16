"""Regression coverage for stable context identity backfill."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import sqlite3
from pathlib import Path

from alembic import command
import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.api.routers.memory.schemas import MemoryCorrectionRecord
from magi.core.workspace import WorkspacePaths, WorkspaceStateStore
from magi.memory.context_scope import (
    ContextCatalog,
    context_id_for_builtin,
    context_id_for_legacy_value,
)
from magi.memory.l2.corrections.models import MemoryCorrection
from magi.memory.l2.corrections.fingerprints import (
    assertion_claim_fingerprint,
    assertion_slot_key,
    canonical_scope_json,
    relationship_claim_fingerprint,
    relationship_triple_id,
    scope_key,
    scope_matches,
)


def _memory_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "memory_shared")
    return _build_config(target, db_path)


def _insert_assertion(
    connection: sqlite3.Connection,
    *,
    assertion_id: str,
    slot_key: str,
    value: str,
    scope: dict,
    source_domain: str = "chat",
    validation_state: str = "stable",
    user_feedback: str | None = None,
    status: str = "active",
    created_at: float = 10,
    updated_at: float = 20,
    valid_from: float = 10,
) -> None:
    connection.execute(
        """
        INSERT INTO tom_trait_assertions(
            assertion_id, entity_id, entity_type, trait_family, trait_name,
            trait_value, confidence_score, evidence_events, volatility_index,
            source_domain, inference_depth, validation_state, first_inferred_at,
            last_validated_at, target_entity_id, target_entity_type, target_scope,
            temporal_scope, user_feedback, status, created_at, updated_at, slot_key,
            claim_fingerprint, version_root_id, valid_from, scope_key, scope_json
        ) VALUES (?, 'user:u1', 'user', 'identity_profile', 'location.home',
                  ?, 0.9, '["event-1"]', 0.1, ?, 'explicit', ?,
                  10, 20, '', '', 'global', 'stable', ?, ?, ?, ?, ?,
                  'legacy-claim', ?, ?, ?, ?)
        """,
        (
            assertion_id,
            value,
            source_domain,
            validation_state,
            user_feedback,
            status,
            created_at,
            updated_at,
            slot_key,
            assertion_id,
            valid_from,
            f"legacy-scope-{assertion_id}",
            json.dumps(scope, ensure_ascii=False),
        ),
    )


def _insert_edge(connection: sqlite3.Connection) -> None:
    scope_json = json.dumps({"activity": "写代码"}, ensure_ascii=False)
    connection.execute(
        """
        INSERT INTO knowledge_graph(
            triple_id, subject_id, subject_type, predicate, object_id, object_type,
            fact_kind, confidence, evidence_event_ids, observation_count,
            first_observed_at, last_observed_at, valid_from, status, created_at,
            updated_at, slot_key, claim_fingerprint, scope_key, scope_json
        ) VALUES (
            'edge-old', 'user:u1', 'user', 'USES_EDITOR', 'software:vscode',
            'software', 'explicit_fact', 0.9, '["event-2"]', 1, 10, 20, 10,
            'active', 10, 20, 'edge-slot', 'legacy-edge-claim',
            'legacy-activity-scope', ?
        )
        """,
        (scope_json,),
    )
    connection.execute(
        """
        INSERT INTO knowledge_graph_versions(
            version_id, triple_id, slot_key, claim_fingerprint, subject_id,
            subject_type, predicate, object_id, object_type, fact_kind,
            confidence, evidence_event_ids, status, valid_from, scope_key,
            scope_json, created_at, governance_complete
        ) VALUES (
            'edge-version-old', 'edge-old', 'edge-slot', 'legacy-version-claim',
            'user:u1', 'user', 'USES_EDITOR', 'software:vscode', 'software',
            'explicit_fact', 0.9, '["event-2"]', 'active', 10,
            'legacy-activity-scope', ?, 20, 1
        )
        """,
        (scope_json,),
    )


def _insert_edge_version(
    connection: sqlite3.Connection,
    *,
    version_id: str,
    triple_id: str,
    scope: dict,
    created_at: float,
) -> None:
    connection.execute(
        """
        INSERT INTO knowledge_graph_versions(
            version_id, triple_id, slot_key, claim_fingerprint, subject_id,
            subject_type, predicate, object_id, object_type, fact_kind,
            confidence, evidence_event_ids, status, valid_from, scope_key,
            scope_json, created_at, governance_complete
        ) VALUES (?, ?, 'history-slot', 'legacy-history-claim', 'user:u1',
                  'user', 'USES_EDITOR', 'software:vscode', 'software',
                  'explicit_fact', 0.9, '["event-history"]', 'deprecated', ?,
                  'legacy-history-scope', ?, ?, 1)
        """,
        (version_id, triple_id, created_at, json.dumps(scope), created_at),
    )


def _insert_current_edge(
    connection: sqlite3.Connection,
    *,
    triple_id: str,
    object_id: str,
    scope: dict,
    updated_at: float,
    valid_from: float = 10,
) -> None:
    connection.execute(
        """
        INSERT INTO knowledge_graph(
            triple_id, subject_id, subject_type, predicate, object_id, object_type,
            fact_kind, confidence, evidence_event_ids, observation_count,
            first_observed_at, last_observed_at, valid_from, status, created_at,
            updated_at, slot_key, claim_fingerprint, scope_key, scope_json
        ) VALUES (?, 'user:u1', 'user', 'USES_EDITOR', ?, 'software',
                  'explicit_fact', 0.9, '[]', 1, 10, ?, ?, 'active', 10, ?,
                  'editor-slot', 'legacy-edge-claim', 'legacy-edge-scope', ?)
        """,
        (
            triple_id,
            object_id,
            updated_at,
            valid_from,
            updated_at,
            json.dumps(scope),
        ),
    )


def _insert_materialized_edge_references(
    connection: sqlite3.Connection,
    *,
    triple_id: str,
    source_revision: int = 0,
) -> None:
    connection.execute(
        """
        INSERT INTO tom_snapshots(
            snapshot_id, entity_id, entity_type, relationship_topology,
            active_record_ids, last_updated_at, created_at, source_revision
        ) VALUES ('snapshot-u1', 'user:u1', 'user', ?, ?, 20, 10, ?)
        """,
        (json.dumps({"primary": triple_id}), json.dumps([triple_id]), source_revision),
    )
    connection.execute(
        """
        INSERT INTO user_portrait_projection(
            user_id, entity_id, evidence_refs_json, generated_at,
            created_at, updated_at, source_revision
        ) VALUES ('u1', 'user:u1', ?, 20, 10, 20, ?)
        """,
        (json.dumps([f"edge:{triple_id}"]), source_revision),
    )
    connection.execute(
        """
        INSERT INTO user_profile_projection(
            user_id, entity_id, field_sources_json, refreshed_at,
            created_at, updated_at, source_revision
        ) VALUES ('u1', 'user:u1', ?, 20, 10, 20, ?)
        """,
        (json.dumps({"editor": f"relationship:{triple_id}"}), source_revision),
    )
    connection.executemany(
        """
        INSERT INTO memory_derivation_dependencies(
            artifact_kind, artifact_id, source_kind, source_id,
            subject_key, source_revision, created_at
        ) VALUES (?, ?, 'edge', ?, 'user:u1', ?, 20)
        """,
        [
            ("snapshot", "snapshot-u1", triple_id, source_revision),
            ("portrait", "u1", triple_id, source_revision),
            ("profile", "u1", triple_id, source_revision),
        ],
    )


def _insert_corrections(connection: sqlite3.Connection) -> None:
    assertion_before = dict(
        connection.execute(
            "SELECT * FROM tom_trait_assertions WHERE assertion_id = 'assert-project'"
        ).fetchone()
    )
    assertion_replacement = {
        "value": "Shanghai",
        "scope": {"project": "Magi"},
    }
    connection.execute(
        """
        INSERT INTO memory_corrections(
            correction_id, request_id, actor_id, target_kind, target_id,
            slot_key, claim_fingerprint, correction_kind, before_json,
            replacement_json, scope_json, replacement_target_id, state, created_at
        ) VALUES (
            'correction-assertion', 'request-assertion', 'user:u1', 'assertion',
            'assert-project', 'assertion-slot', 'legacy-assertion-claim',
            'scope_refinement', ?, ?, ?, 'assert-project-new', 'active', 30
        )
        """,
        (
            json.dumps(assertion_before, ensure_ascii=False),
            json.dumps(assertion_replacement, ensure_ascii=False),
            json.dumps({"project": "Magi"}, ensure_ascii=False),
        ),
    )
    connection.executemany(
        """
        INSERT INTO memory_correction_rules(
            rule_id, correction_id, target_kind, rule_kind, slot_key,
            claim_fingerprint, scope_key, active, created_at
        ) VALUES (?, 'correction-assertion', 'assertion', ?, 'assertion-slot',
                  'legacy-rule-claim', 'legacy-rule-scope', 1, 30)
        """,
        [
            ("rule-assertion-scope", "scope_only"),
            ("rule-assertion-authoritative", "authoritative_slot"),
        ],
    )

    edge_before = dict(
        connection.execute("SELECT * FROM knowledge_graph WHERE triple_id = 'edge-old'").fetchone()
    )
    edge_replacement = {
        "triple_id": "edge-new",
        "subject_id": "user:u1",
        "subject_type": "user",
        "predicate": "USES_EDITOR",
        "object_id": "software:zed",
        "object_type": "software",
        "fact_kind": "explicit_fact",
        "slot_key": "edge-slot",
        "claim_fingerprint": "legacy-edge-replacement-claim",
        "scope_key": "legacy-place-scope",
        "scope_json": json.dumps({"place": "公司"}, ensure_ascii=False),
        "valid_from": 30,
    }
    connection.execute(
        """
        INSERT INTO memory_corrections(
            correction_id, request_id, actor_id, target_kind, target_id,
            slot_key, claim_fingerprint, correction_kind, before_json,
            replacement_json, scope_json, replacement_target_id, state, created_at
        ) VALUES (
            'correction-edge', 'request-edge', 'user:u1', 'edge', 'edge-old',
            'edge-slot', 'legacy-edge-claim', 'scope_refinement', ?, ?, ?,
            'edge-new', 'active', 30
        )
        """,
        (
            json.dumps(edge_before, ensure_ascii=False),
            json.dumps(edge_replacement, ensure_ascii=False),
            json.dumps({"place": "公司"}, ensure_ascii=False),
        ),
    )
    connection.executemany(
        """
        INSERT INTO memory_correction_rules(
            rule_id, correction_id, target_kind, rule_kind, slot_key,
            claim_fingerprint, scope_key, active, created_at
        ) VALUES (?, 'correction-edge', 'edge', ?, 'edge-slot',
                  'legacy-edge-rule-claim', 'legacy-edge-rule-scope', 1, 30)
        """,
        [
            ("rule-edge-scope", "scope_only"),
            ("rule-edge-authoritative", "authoritative_slot"),
        ],
    )


def test_v13_migrates_claims_snapshots_replacements_rules_and_custom_scopes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v12_scheduled_correction_transitions")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        _insert_assertion(
            connection,
            assertion_id="assert-project",
            slot_key="assertion-slot",
            value="Hangzhou",
            scope={"project": "Magi"},
        )
        _insert_assertion(
            connection,
            assertion_id="assert-time",
            slot_key="time-slot",
            value="Night",
            scope={"time_range": {"start": "22:00", "end": "23:00"}},
        )
        _insert_edge(connection)
        _insert_materialized_edge_references(connection, triple_id="edge-old")
        _insert_corrections(connection)
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        assertions = {
            str(row["assertion_id"]): dict(row)
            for row in connection.execute("SELECT * FROM tom_trait_assertions")
        }
        project_scope = json.loads(assertions["assert-project"]["scope_json"])
        time_scope = json.loads(assertions["assert-time"]["scope_json"])
        assert project_scope["all_of"][0]["dimension"] == "project"
        assert time_scope["all_of"][0]["dimension"] == "time"
        assert assertions["assert-time"]["scope_key"] != "global"
        assert canonical_scope_json(time_scope) == assertions["assert-time"]["scope_json"]

        edge = dict(connection.execute("SELECT * FROM knowledge_graph").fetchone())
        edge_version = dict(
            connection.execute(
                "SELECT * FROM knowledge_graph_versions WHERE version_id = 'edge-version-old'"
            ).fetchone()
        )
        activity_scope = json.loads(edge["scope_json"])
        expected_edge_id = relationship_triple_id(
            subject_id="user:u1",
            predicate="USES_EDITOR",
            object_id="software:vscode",
            scope_key_value=scope_key(activity_scope),
        )
        assert edge["triple_id"] == expected_edge_id
        assert edge_version["triple_id"] == expected_edge_id
        assert {
            row[0]
            for row in connection.execute(
                """
                SELECT source_id FROM memory_derivation_dependencies
                WHERE source_kind = 'edge'
                """
            )
        } == {expected_edge_id}
        assert json.loads(
            connection.execute(
                """
                SELECT active_record_ids FROM tom_snapshots
                WHERE snapshot_id = 'snapshot-u1'
                """
            ).fetchone()[0]
        ) == [expected_edge_id]
        assert json.loads(
            connection.execute(
                """
                SELECT evidence_refs_json FROM user_portrait_projection
                WHERE user_id = 'u1'
                """
            ).fetchone()[0]
        ) == [f"edge:{expected_edge_id}"]
        assert activity_scope["all_of"][0]["dimension"] == "activity"
        assert edge_version["scope_json"] == edge["scope_json"]
        assert edge_version["claim_fingerprint"] == edge["claim_fingerprint"]

        assertion_correction = dict(
            connection.execute(
                "SELECT * FROM memory_corrections WHERE correction_id = 'correction-assertion'"
            ).fetchone()
        )
        assertion_before = json.loads(assertion_correction["before_json"])
        assertion_replacement = json.loads(assertion_correction["replacement_json"])
        replacement_scope = assertion_replacement["scope"]
        before_scope = json.loads(assertion_before["scope_json"])
        assert before_scope == project_scope == replacement_scope
        expected_before_fingerprint = assertion_claim_fingerprint(
            slot_key_value="assertion-slot",
            trait_value="Hangzhou",
            scope_key_value=scope_key(project_scope),
        )
        expected_replacement_fingerprint = assertion_claim_fingerprint(
            slot_key_value="assertion-slot",
            trait_value="Shanghai",
            scope_key_value=scope_key(replacement_scope),
        )
        assert assertion_correction["claim_fingerprint"] == expected_before_fingerprint
        assertion_rules = {
            str(row["rule_kind"]): dict(row)
            for row in connection.execute(
                "SELECT * FROM memory_correction_rules WHERE correction_id = 'correction-assertion'"
            )
        }
        assert assertion_rules["scope_only"]["claim_fingerprint"] == expected_before_fingerprint
        assert assertion_rules["scope_only"]["scope_key"] == scope_key(replacement_scope)
        assert (
            assertion_rules["authoritative_slot"]["claim_fingerprint"]
            == expected_replacement_fingerprint
        )

        edge_correction = dict(
            connection.execute(
                "SELECT * FROM memory_corrections WHERE correction_id = 'correction-edge'"
            ).fetchone()
        )
        edge_before = json.loads(edge_correction["before_json"])
        edge_replacement = json.loads(edge_correction["replacement_json"])
        edge_before_scope = json.loads(edge_before["scope_json"])
        edge_replacement_scope = json.loads(edge_replacement["scope_json"])
        expected_replacement_id = relationship_triple_id(
            subject_id="user:u1",
            predicate="USES_EDITOR",
            object_id="software:zed",
            scope_key_value=scope_key(edge_replacement_scope),
        )
        assert edge_correction["target_id"] == expected_edge_id
        assert edge_correction["replacement_target_id"] == expected_replacement_id
        assert edge_before["triple_id"] == expected_edge_id
        assert edge_replacement["triple_id"] == expected_replacement_id
        expected_edge_before = relationship_claim_fingerprint(
            slot_key_value="edge-slot",
            subject_id="user:u1",
            predicate="USES_EDITOR",
            object_id="software:vscode",
            scope_key_value=scope_key(edge_before_scope),
        )
        expected_edge_replacement = relationship_claim_fingerprint(
            slot_key_value="edge-slot",
            subject_id="user:u1",
            predicate="USES_EDITOR",
            object_id="software:zed",
            scope_key_value=scope_key(edge_replacement_scope),
        )
        assert edge_correction["claim_fingerprint"] == expected_edge_before
        assert edge_replacement["claim_fingerprint"] == expected_edge_replacement
        edge_rules = {
            str(row["rule_kind"]): dict(row)
            for row in connection.execute(
                "SELECT * FROM memory_correction_rules WHERE correction_id = 'correction-edge'"
            )
        }
        assert edge_rules["scope_only"]["claim_fingerprint"] == expected_edge_before
        assert edge_rules["scope_only"]["scope_key"] == scope_key(edge_replacement_scope)
        assert edge_rules["authoritative_slot"]["claim_fingerprint"] == expected_edge_replacement

        project_context_id = project_scope["all_of"][0]["context_id"]
        custom_sources = dict(
            connection.execute(
                "SELECT dimension, source_kind FROM memory_context_catalog"
            ).fetchall()
        )
        assert custom_sources["time"] == "legacy_custom"
        assert custom_sources["place"] == "legacy_custom"
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    workspace = tmp_path / "Magi"
    workspace.mkdir()
    WorkspaceStateStore(WorkspacePaths.from_root(workspace)).claim_identity()
    option = asyncio.run(ContextCatalog(str(db_path)).register_workspace(str(workspace)))
    assert option is not None
    assert option.context_id != project_context_id
    assert not scope_matches(
        project_scope,
        {"all_of": [{"dimension": "project", "context_id": option.context_id}]},
    )

    with sqlite3.connect(db_path) as connection:
        source_kind, binding_count = connection.execute(
            """
            SELECT catalog.source_kind, COUNT(bindings.binding_id)
            FROM memory_context_catalog AS catalog
            LEFT JOIN memory_context_bindings AS bindings
              ON bindings.context_id = catalog.context_id
            WHERE catalog.context_id = ?
            GROUP BY catalog.context_id
            """,
            (project_context_id,),
        ).fetchone()
    assert (source_kind, binding_count) == ("legacy_custom", 0)


def test_fresh_memory_schema_uses_scoped_relationship_uniqueness(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    asyncio.run(apply_memory_shared_schema(str(db_path)))

    insert_sql = """
        INSERT INTO knowledge_graph(
            triple_id, subject_id, subject_type, predicate, object_id, object_type,
            evidence_event_ids, first_observed_at, last_observed_at,
            created_at, updated_at, scope_key, scope_json
        ) VALUES (?, 'user:u1', 'user', 'USES_EDITOR', 'software:vscode',
                  'software', '[]', 10, 10, 10, 10, ?, ?)
    """
    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute(
                """
            SELECT COUNT(*) FROM memory_context_catalog
            WHERE dimension = 'activity' AND source_kind = 'built_in'
            """
            ).fetchone()[0]
            == 1
        )
        connection.execute(insert_sql, ("edge-global", "global", "{}"))
        connection.execute(
            insert_sql,
            (
                "edge-project",
                "scope_project",
                json.dumps({"project": "Magi"}),
            ),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                insert_sql,
                (
                    "edge-project-duplicate",
                    "scope_project",
                    json.dumps({"project": "Magi"}),
                ),
            )


@pytest.mark.parametrize("correction_kind", ["record_error", "situation_changed"])
def test_v13_non_scope_corrections_inherit_the_before_scope(
    tmp_path: Path,
    correction_kind: str,
) -> None:
    db_path = tmp_path / f"{correction_kind}.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v12_scheduled_correction_transitions")
    before_scope = {"project": "Magi"}
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                replacement_json, scope_json, replacement_target_id, state,
                created_at
            ) VALUES (
                'correction-inherited-scope', 'request-inherited-scope',
                'user:u1', 'assertion', 'assertion-old', 'assertion-slot',
                'legacy-before-claim', ?, ?, ?, ?, 'assertion-new', 'active', 30
            )
            """,
            (
                correction_kind,
                json.dumps(
                    {
                        "trait_value": "Hangzhou",
                        "scope_json": json.dumps(before_scope),
                    }
                ),
                json.dumps({"value": "Shanghai", "scope": {"place": "Office"}}),
                json.dumps({"person": "Alice"}),
            ),
        )
        connection.execute(
            """
            INSERT INTO memory_correction_rules(
                rule_id, correction_id, target_kind, rule_kind, slot_key,
                claim_fingerprint, scope_key, active, created_at
            ) VALUES (
                'rule-inherited-scope', 'correction-inherited-scope', 'assertion',
                'authoritative_slot', 'assertion-slot', 'legacy-new-claim',
                'legacy-replacement-scope', 1, 30
            )
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        correction = connection.execute(
            """
            SELECT scope_json, before_json, replacement_json
            FROM memory_corrections
            WHERE correction_id = 'correction-inherited-scope'
            """
        ).fetchone()
        rule_scope_key = connection.execute(
            """
            SELECT scope_key FROM memory_correction_rules
            WHERE rule_id = 'rule-inherited-scope'
            """
        ).fetchone()[0]
        ignored_scope_contexts = connection.execute(
            """
            SELECT COUNT(*) FROM memory_context_catalog
            WHERE dimension IN ('person', 'place')
            """
        ).fetchone()[0]
    migrated_before = json.loads(json.loads(correction["before_json"])["scope_json"])
    migrated_replacement = json.loads(correction["replacement_json"])["scope"]
    assert json.loads(correction["scope_json"]) == migrated_before
    assert migrated_replacement == migrated_before
    assert rule_scope_key == scope_key(migrated_before)
    assert ignored_scope_contexts == 0


def test_v13_non_scope_edge_history_inherits_the_before_scope(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "edge-inherited-scope.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v12_scheduled_correction_transitions")
    before_scope = {"project": "Magi"}
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        _insert_current_edge(
            connection,
            triple_id="edge-before",
            object_id="software:vscode",
            scope=before_scope,
            updated_at=20,
        )
        before = dict(
            connection.execute(
                "SELECT * FROM knowledge_graph WHERE triple_id = 'edge-before'"
            ).fetchone()
        )
        replacement = {
            "triple_id": "edge-replacement",
            "subject_id": "user:u1",
            "subject_type": "user",
            "predicate": "USES_EDITOR",
            "object_id": "software:zed",
            "object_type": "software",
            "fact_kind": "explicit_fact",
            "slot_key": "editor-slot",
            "scope_json": json.dumps({"place": "Office"}),
        }
        connection.execute(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                replacement_json, scope_json, replacement_target_id, state,
                created_at
            ) VALUES (
                'correction-edge-inherited', 'request-edge-inherited', 'user:u1',
                'edge', 'edge-before', 'editor-slot', 'legacy-before-claim',
                'record_error', ?, ?, ?, 'edge-replacement', 'active', 30
            )
            """,
            (
                json.dumps(before),
                json.dumps(replacement),
                json.dumps({"person": "Alice"}),
            ),
        )
        _insert_edge_version(
            connection,
            version_id="replacement-history",
            triple_id="edge-replacement",
            scope={"place": "Office"},
            created_at=30,
        )
        connection.execute(
            """
            UPDATE knowledge_graph_versions
            SET correction_id = 'correction-edge-inherited'
            WHERE version_id = 'replacement-history'
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        correction = connection.execute(
            """
            SELECT scope_json, replacement_json FROM memory_corrections
            WHERE correction_id = 'correction-edge-inherited'
            """
        ).fetchone()
        version_scope_json = connection.execute(
            """
            SELECT scope_json FROM knowledge_graph_versions
            WHERE version_id = 'replacement-history'
            """
        ).fetchone()[0]
    correction_scope = json.loads(correction[0])
    replacement_scope = json.loads(json.loads(correction[1])["scope_json"])
    version_scope = json.loads(version_scope_json)
    assert correction_scope == replacement_scope == version_scope
    assert correction_scope["all_of"][0]["dimension"] == "project"


def test_v13_rekeys_history_only_relationship_references(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "history-only.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v12_scheduled_correction_transitions")
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        _insert_edge_version(
            connection,
            version_id="history-only-version",
            triple_id="history-only-edge",
            scope={"activity": "coding"},
            created_at=20,
        )
        _insert_materialized_edge_references(
            connection,
            triple_id="history-only-edge",
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        version = connection.execute(
            """
            SELECT triple_id, scope_key FROM knowledge_graph_versions
            WHERE version_id = 'history-only-version'
            """
        ).fetchone()
        expected_id = relationship_triple_id(
            subject_id="user:u1",
            predicate="USES_EDITOR",
            object_id="software:vscode",
            scope_key_value=version["scope_key"],
        )
        assert version["triple_id"] == expected_id
        assert {
            row[0]
            for row in connection.execute(
                """
                SELECT source_id FROM memory_derivation_dependencies
                WHERE source_kind = 'edge'
                """
            )
        } == {expected_id}
        snapshot = connection.execute(
            """
            SELECT relationship_topology, active_record_ids
            FROM tom_snapshots WHERE snapshot_id = 'snapshot-u1'
            """
        ).fetchone()
        portrait_refs = json.loads(
            connection.execute(
                """
                SELECT evidence_refs_json FROM user_portrait_projection
                WHERE user_id = 'u1'
                """
            ).fetchone()[0]
        )
        profile_sources = json.loads(
            connection.execute(
                """
                SELECT field_sources_json FROM user_profile_projection
                WHERE user_id = 'u1'
                """
            ).fetchone()[0]
        )
    assert json.loads(snapshot["relationship_topology"])["primary"] == expected_id
    assert json.loads(snapshot["active_record_ids"]) == [expected_id]
    assert portrait_refs == [f"edge:{expected_id}"]
    assert profile_sources == {"editor": f"relationship:{expected_id}"}


def test_v13_merges_existing_target_dependency_revision_on_rekey(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "dependency-merge.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v12_scheduled_correction_transitions")
    coding_scope = {
        "all_of": [
            {
                "dimension": "activity",
                "context_id": context_id_for_builtin("activity", "Coding"),
            }
        ]
    }
    expected_id = relationship_triple_id(
        subject_id="user:u1",
        predicate="USES_EDITOR",
        object_id="software:vscode",
        scope_key_value=scope_key(coding_scope),
    )
    with sqlite3.connect(db_path) as connection:
        _insert_edge_version(
            connection,
            version_id="dependency-merge-version",
            triple_id="dependency-merge-edge",
            scope={"activity": "coding"},
            created_at=20,
        )
        _insert_materialized_edge_references(
            connection,
            triple_id="dependency-merge-edge",
            source_revision=5,
        )
        connection.execute(
            """
            INSERT INTO memory_derivation_dependencies(
                artifact_kind, artifact_id, source_kind, source_id,
                subject_key, source_revision, created_at
            ) VALUES ('snapshot', 'snapshot-u1', 'edge', ?, 'user:u1', 1, 10)
            """,
            (expected_id,),
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        dependency = connection.execute(
            """
            SELECT source_revision, created_at
            FROM memory_derivation_dependencies
            WHERE artifact_kind = 'snapshot'
              AND artifact_id = 'snapshot-u1'
              AND source_kind = 'edge'
              AND source_id = ?
            """,
            (expected_id,),
        ).fetchone()
    assert dependency == (5, 10.0)


def test_v13_invalidates_ambiguous_history_only_relationship_references(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "ambiguous-history.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v12_scheduled_correction_transitions")
    with sqlite3.connect(db_path) as connection:
        _insert_edge_version(
            connection,
            version_id="history-project-a",
            triple_id="ambiguous-history-edge",
            scope={"project": "Project A"},
            created_at=10,
        )
        _insert_edge_version(
            connection,
            version_id="history-project-b",
            triple_id="ambiguous-history-edge",
            scope={"project": "Project B"},
            created_at=20,
        )
        _insert_materialized_edge_references(
            connection,
            triple_id="ambiguous-history-edge",
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        migrated_ids = {
            row[0]
            for row in connection.execute(
                """
                SELECT triple_id FROM knowledge_graph_versions
                WHERE version_id IN ('history-project-a', 'history-project-b')
                """
            )
        }
        dependency_ids = {
            row[0]
            for row in connection.execute(
                """
                SELECT source_id FROM memory_derivation_dependencies
                WHERE source_kind = 'edge'
                """
            )
        }
        subject_revision = connection.execute(
            """
            SELECT revision FROM memory_subject_revisions
            WHERE subject_key = 'user:u1'
            """
        ).fetchone()[0]
        artifact_revisions = {
            connection.execute(
                """
                SELECT source_revision FROM tom_snapshots
                WHERE snapshot_id = 'snapshot-u1'
                """
            ).fetchone()[0],
            connection.execute(
                """
                SELECT source_revision FROM user_profile_projection
                WHERE user_id = 'u1'
                """
            ).fetchone()[0],
            connection.execute(
                """
                SELECT source_revision FROM user_portrait_projection
                WHERE user_id = 'u1'
                """
            ).fetchone()[0],
        }
        snapshot_reference = json.loads(
            connection.execute(
                """
                SELECT active_record_ids FROM tom_snapshots
                WHERE snapshot_id = 'snapshot-u1'
                """
            ).fetchone()[0]
        )
    assert len(migrated_ids) == 2
    assert dependency_ids == migrated_ids
    assert subject_revision > max(artifact_revisions)
    assert snapshot_reference == ["ambiguous-history-edge"]


def test_v13_retires_authority_and_derivations_for_edge_scope_collisions(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "edge-collision.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v12_scheduled_correction_transitions")
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        _insert_current_edge(
            connection,
            triple_id="edge-coding",
            object_id="software:vscode",
            scope={"activity": "coding"},
            updated_at=20,
        )
        _insert_current_edge(
            connection,
            triple_id="edge-code",
            object_id="software:zed",
            scope={"activity": "code"},
            updated_at=40,
            valid_from=40,
        )
        _insert_materialized_edge_references(
            connection,
            triple_id="edge-coding",
        )
        before = dict(
            connection.execute(
                "SELECT * FROM knowledge_graph WHERE triple_id = 'edge-code'"
            ).fetchone()
        )
        replacement = {
            "triple_id": "edge-coding",
            "subject_id": "user:u1",
            "subject_type": "user",
            "predicate": "USES_EDITOR",
            "object_id": "software:vscode",
            "object_type": "software",
            "fact_kind": "explicit_fact",
            "slot_key": "editor-slot",
            "claim_fingerprint": "legacy-edge-claim",
            "scope_key": "legacy-edge-scope",
            "scope_json": json.dumps({"activity": "coding"}),
        }
        connection.execute(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                replacement_json, scope_json, replacement_target_id, state,
                created_at
            ) VALUES (
                'correction-edge-collision', 'request-edge-collision', 'user:u1',
                'edge', 'edge-code', 'editor-slot', 'legacy-before-claim',
                'scope_refinement', ?, ?, ?, 'edge-coding', 'active', 50
            )
            """,
            (
                json.dumps(before),
                json.dumps(replacement),
                json.dumps({"activity": "coding"}),
            ),
        )
        connection.executemany(
            """
            INSERT INTO memory_correction_rules(
                rule_id, correction_id, target_kind, rule_kind, slot_key,
                claim_fingerprint, scope_key, active, created_at
            ) VALUES (?, 'correction-edge-collision', 'edge', ?, 'editor-slot',
                      'legacy-edge-claim', 'legacy-edge-scope', 1, 50)
            """,
            [
                ("rule-edge-collision-authority", "authoritative_slot"),
                ("rule-edge-collision-block", "block_claim"),
            ],
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = {
            row["object_id"]: dict(row)
            for row in connection.execute(
                """
                SELECT triple_id, object_id, status, status_reason
                FROM knowledge_graph
                """
            )
        }
        loser = rows["software:vscode"]
        winner = rows["software:zed"]
        replacement_target_id = connection.execute(
            """
            SELECT replacement_target_id FROM memory_corrections
            WHERE correction_id = 'correction-edge-collision'
            """
        ).fetchone()[0]
        active_rule_kinds = {
            row[0]
            for row in connection.execute(
                """
            SELECT rule_kind FROM memory_correction_rules
            WHERE correction_id = 'correction-edge-collision' AND active = 1
            """
            )
        }
        subject_revision = connection.execute(
            """
            SELECT revision FROM memory_subject_revisions
            WHERE subject_key = 'user:u1'
            """
        ).fetchone()[0]
        loser_versions = [
            dict(row)
            for row in connection.execute(
                """
                SELECT version_id, previous_version_id, status, valid_from,
                       valid_to, created_at
                FROM knowledge_graph_versions
                WHERE triple_id = ?
                ORDER BY created_at, version_id
                """,
                (loser["triple_id"],),
            )
        ]
    assert winner["status"] == "active"
    assert loser["status"] == "deprecated"
    assert loser["status_reason"] == "v13_scope_alias_collision"
    assert replacement_target_id == loser["triple_id"]
    assert active_rule_kinds == {"block_claim"}
    assert subject_revision > 0
    assert [row["status"] for row in loser_versions[-2:]] == [
        "active",
        "deprecated",
    ]
    assert loser_versions[-2]["valid_to"] is None
    assert loser_versions[-1]["valid_to"] == 40
    assert loser_versions[-1]["previous_version_id"] == loser_versions[-2]["version_id"]

    from magi.memory.l2.store import L2CognitionStore

    coding_scope = {
        "all_of": [
            {
                "dimension": "activity",
                "context_id": context_id_for_builtin("activity", "coding"),
            }
        ]
    }
    historical = asyncio.run(
        L2CognitionStore(db_path=str(db_path)).list_current_relationships(
            subject_id="user:u1",
            context_scope=coding_scope,
            effective_at=20,
        )
    )
    assert [item["object_id"] for item in historical] == ["software:vscode"]


def test_v13_preserves_scope_only_when_a_scoped_replacement_loses_a_collision(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "scope-only-collision.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v12_scheduled_correction_transitions")
    slot_key_value = assertion_slot_key(
        entity_type="user",
        entity_id="user:u1",
        trait_name="location.home",
    )
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        _insert_assertion(
            connection,
            assertion_id="assert-source-home",
            slot_key=slot_key_value,
            value="First",
            scope={"place": "home"},
            status="superseded",
            created_at=10,
            updated_at=30,
            valid_from=10,
        )
        _insert_assertion(
            connection,
            assertion_id="assert-corrected-coding",
            slot_key=slot_key_value,
            value="First",
            scope={"activity": "coding"},
            user_feedback="confirmed",
            created_at=30,
            updated_at=30,
            valid_from=30,
        )
        _insert_assertion(
            connection,
            assertion_id="assert-newer-code",
            slot_key=slot_key_value,
            value="Second",
            scope={"activity": "code"},
            user_feedback="confirmed",
            created_at=40,
            updated_at=40,
            valid_from=40,
        )
        connection.execute(
            """
            UPDATE tom_trait_assertions
            SET superseded_by = 'assert-corrected-coding', superseded_at = 30,
                valid_to = 30
            WHERE assertion_id = 'assert-source-home'
            """
        )
        before = dict(
            connection.execute(
                """
                SELECT * FROM tom_trait_assertions
                WHERE assertion_id = 'assert-source-home'
                """
            ).fetchone()
        )
        connection.execute(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                replacement_json, scope_json, replacement_target_id, state,
                created_at
            ) VALUES (
                'correction-scope-only-collision',
                'request-scope-only-collision', 'user:u1', 'assertion',
                'assert-source-home', ?, 'legacy-source-claim',
                'scope_refinement', ?, ?, ?, 'assert-corrected-coding',
                'active', 30
            )
            """,
            (
                slot_key_value,
                json.dumps(before),
                json.dumps(
                    {
                        "value": "First",
                        "scope": {"activity": "coding"},
                    }
                ),
                json.dumps({"activity": "coding"}),
            ),
        )
        connection.executemany(
            """
            INSERT INTO memory_correction_rules(
                rule_id, correction_id, target_kind, rule_kind, slot_key,
                claim_fingerprint, scope_key, active, created_at
            ) VALUES (?, 'correction-scope-only-collision', 'assertion', ?, ?,
                      'legacy-source-claim', 'legacy-source-scope', 1, 30)
            """,
            [
                (
                    "rule-scope-only-collision",
                    "scope_only",
                    slot_key_value,
                ),
                (
                    "rule-authority-collision",
                    "authoritative_slot",
                    slot_key_value,
                ),
            ],
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        active_rules = {
            str(row["rule_kind"]): dict(row)
            for row in connection.execute(
                """
                SELECT rule_kind, claim_fingerprint, scope_key
                FROM memory_correction_rules
                WHERE correction_id = 'correction-scope-only-collision'
                  AND active = 1
                """
            )
        }
        corrected_status = str(
            connection.execute(
                """
                SELECT status FROM tom_trait_assertions
                WHERE assertion_id = 'assert-corrected-coding'
                """
            ).fetchone()[0]
        )
    assert corrected_status == "superseded"
    assert set(active_rules) == {"scope_only"}

    source_scope = {
        "all_of": [
            {
                "dimension": "place",
                "context_id": context_id_for_legacy_value("place", "home"),
            }
        ]
    }
    from magi.memory.l2.store import L2CognitionStore

    replayed_id = asyncio.run(
        L2CognitionStore(db_path=str(db_path)).upsert_assertion_candidate(
            {
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "identity_profile",
                "trait_name": "location.home",
                "trait_value": "First",
                "confidence_score": 0.9,
                "evidence_events": ["event-source-replay"],
                "volatility_index": 0.1,
                "source_domain": "conversation",
                "inference_depth": "explicit",
                "validation_state": "stable",
                "first_inferred_at": 50,
                "last_validated_at": 50,
                "temporal_scope": "persistent",
                "scope": source_scope,
            }
        )
    )
    assert replayed_id == "assert-source-home"
    with sqlite3.connect(db_path) as connection:
        source = connection.execute(
            """
            SELECT status, evidence_events FROM tom_trait_assertions
            WHERE assertion_id = 'assert-source-home'
            """
        ).fetchone()
    assert source[0] == "superseded"
    assert json.loads(source[1]) == ["event-1"]


def test_v13_resolves_normalization_collisions_and_quarantines_malformed_scopes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v12_scheduled_correction_transitions")
    duplicate_project_scope = {
        "all_of": [
            {"dimension": "project", "context_id": f"ctx_project_{'a' * 64}"},
            {"dimension": "project", "context_id": f"ctx_project_{'b' * 64}"},
        ]
    }
    orphan_context_id = f"ctx_project_{'c' * 64}"

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        _insert_assertion(
            connection,
            assertion_id="assert-coding",
            slot_key="collision-slot",
            value="First",
            scope={"activity": "coding"},
        )
        _insert_assertion(
            connection,
            assertion_id="assert-code",
            slot_key="collision-slot",
            value="First",
            scope={"activity": "code"},
        )
        connection.execute(
            """
            UPDATE tom_trait_assertions
            SET updated_at = 50, valid_from = 40
            WHERE assertion_id = 'assert-code'
            """
        )
        _insert_assertion(
            connection,
            assertion_id="assert-empty-all-of",
            slot_key="malformed-empty-slot",
            value="Empty",
            scope={"all_of": []},
        )
        _insert_assertion(
            connection,
            assertion_id="assert-duplicate-dimension",
            slot_key="malformed-duplicate-slot",
            value="Duplicate",
            scope=duplicate_project_scope,
        )
        _insert_assertion(
            connection,
            assertion_id="assert-json-null",
            slot_key="malformed-null-slot",
            value="Null",
            scope=None,  # type: ignore[arg-type]
        )
        _insert_assertion(
            connection,
            assertion_id="assert-empty-json",
            slot_key="malformed-empty-json-slot",
            value="Empty JSON",
            scope={},
        )
        _insert_assertion(
            connection,
            assertion_id="assert-nested-project",
            slot_key="malformed-nested-slot",
            value="Nested",
            scope={"project": {"name": "Magi"}},
        )
        _insert_assertion(
            connection,
            assertion_id="assert-list-project",
            slot_key="malformed-list-slot",
            value="List",
            scope={"project": ["Magi"]},
        )
        _insert_assertion(
            connection,
            assertion_id="assert-blank-project",
            slot_key="malformed-blank-slot",
            value="Blank",
            scope={"project": "   "},
        )
        _insert_assertion(
            connection,
            assertion_id="assert-unknown-field",
            slot_key="malformed-unknown-slot",
            value="Unknown",
            scope={"unexpected": "unexpected-secret"},
        )
        _insert_assertion(
            connection,
            assertion_id="assert-broken-json",
            slot_key="malformed-broken-json-slot",
            value="Broken JSON",
            scope={},
        )
        _insert_assertion(
            connection,
            assertion_id="assert-orphan-identity",
            slot_key="orphan-identity-slot",
            value="Orphan",
            scope={
                "all_of": [
                    {
                        "dimension": "project",
                        "context_id": orphan_context_id,
                    }
                ]
            },
        )
        _insert_assertion(
            connection,
            assertion_id="assert-invalid-json-marker",
            slot_key="quarantine-collision-slot",
            value="Invalid JSON",
            scope={},
        )
        _insert_assertion(
            connection,
            assertion_id="assert-decoded-invalid-json-marker",
            slot_key="quarantine-collision-slot",
            value="Decoded marker",
            scope={"invalid_scope_json": "x"},
        )
        connection.execute(
            """
            UPDATE tom_trait_assertions SET scope_json = ''
            WHERE assertion_id = 'assert-empty-json'
            """
        )
        connection.execute(
            """
            UPDATE tom_trait_assertions SET scope_json = '{broken-secret'
            WHERE assertion_id = 'assert-broken-json'
            """
        )
        connection.execute(
            """
            UPDATE tom_trait_assertions SET scope_json = 'x'
            WHERE assertion_id = 'assert-invalid-json-marker'
            """
        )
        collision_before = dict(
            connection.execute(
                """
                SELECT * FROM tom_trait_assertions
                WHERE assertion_id = 'assert-code'
                """
            ).fetchone()
        )
        connection.execute(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                replacement_json, scope_json, replacement_target_id, state,
                created_at
            ) VALUES (
                'correction-collision-loser', 'request-collision-loser',
                'user:u1', 'assertion', 'assert-code', 'collision-slot',
                'legacy-before-claim', 'scope_refinement', ?, ?, ?,
                'assert-coding', 'active', 60
            )
            """,
            (
                json.dumps(collision_before),
                json.dumps({"value": "First", "scope": {"activity": "coding"}}),
                json.dumps({"activity": "coding"}),
            ),
        )
        connection.executemany(
            """
            INSERT INTO memory_correction_rules(
                rule_id, correction_id, target_kind, rule_kind, slot_key,
                claim_fingerprint, scope_key, active, created_at
            ) VALUES (?, 'correction-collision-loser', 'assertion', ?,
                      'collision-slot', 'legacy-collision-claim',
                      'legacy-collision-scope', 1, 60)
            """,
            [
                ("rule-collision-scope", "scope_only"),
                ("rule-collision-authority", "authoritative_slot"),
            ],
        )
        connection.execute(
            """
            INSERT INTO tom_snapshots(
                snapshot_id, entity_id, entity_type, active_record_ids,
                last_updated_at, created_at, source_revision
            ) VALUES ('snapshot-collision', 'user:u1', 'user',
                      '["assert-coding"]', 60, 60, 0)
            """
        )
        connection.execute(
            """
            INSERT INTO summaries(
                summary_id, summary_type, summary_category, period_start,
                period_end, content, source_event_ids, source_event_count,
                created_at, updated_at, source_revision, derivation_state
            ) VALUES ('insight-collision', 'insight', 'identity', 0, 60,
                      'Legacy collision insight', '[]', 0, 60, 60, 0, 'current')
            """
        )
        connection.execute(
            """
            INSERT INTO user_portrait_projection(
                user_id, entity_id, evidence_refs_json, generated_at,
                created_at, updated_at, source_revision
            ) VALUES ('u2', 'user:u2', '["assertion:assert-coding"]',
                      60, 60, 60, 7)
            """
        )
        connection.executemany(
            """
            INSERT INTO memory_derivation_dependencies(
                artifact_kind, artifact_id, source_kind, source_id,
                subject_key, source_revision, created_at
            ) VALUES (?, ?, 'assertion', 'assert-coding', 'user:u1', 0, 60)
            """,
            [
                ("snapshot", "snapshot-collision"),
                ("l3_insight", "insight-collision"),
            ],
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        collision_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT assertion_id, status, superseded_by, valid_to,
                       scope_key, scope_json
                FROM tom_trait_assertions
                WHERE slot_key = 'collision-slot'
                ORDER BY assertion_id
                """
            )
        ]
        assert collision_rows[0]["assertion_id"] == "assert-code"
        assert collision_rows[0]["status"] == "active"
        assert collision_rows[1]["assertion_id"] == "assert-coding"
        assert collision_rows[1]["status"] == "superseded"
        assert collision_rows[1]["superseded_by"] == "assert-code"
        assert collision_rows[1]["valid_to"] == 50
        assert collision_rows[0]["scope_key"] == collision_rows[1]["scope_key"]
        assert collision_rows[0]["scope_json"] == collision_rows[1]["scope_json"]
        assert (
            connection.execute(
                """
            SELECT COUNT(*) FROM memory_correction_rules
            WHERE correction_id = 'correction-collision-loser' AND active = 1
            """
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                """
            SELECT derivation_state FROM summaries
            WHERE summary_id = 'insight-collision'
            """
            ).fetchone()[0]
            == "stale"
        )
        assert (
            connection.execute(
                """
            SELECT revision FROM memory_subject_revisions
            WHERE subject_key = 'user:u1'
            """
            ).fetchone()[0]
            > 0
        )
        assert (
            connection.execute(
                """
            SELECT revision FROM memory_subject_revisions
            WHERE subject_key = 'user:u2'
            """
            ).fetchone()[0]
            > 7
        )

        for assertion_id in (
            "assert-empty-all-of",
            "assert-duplicate-dimension",
            "assert-json-null",
            "assert-empty-json",
            "assert-nested-project",
            "assert-list-project",
            "assert-blank-project",
            "assert-unknown-field",
            "assert-broken-json",
            "assert-invalid-json-marker",
            "assert-decoded-invalid-json-marker",
        ):
            row = connection.execute(
                """
                SELECT scope_key, scope_json
                FROM tom_trait_assertions
                WHERE assertion_id = ?
                """,
                (assertion_id,),
            ).fetchone()
            migrated_scope = json.loads(row["scope_json"])
            assert canonical_scope_json(migrated_scope) == row["scope_json"]
            assert migrated_scope["all_of"][0]["dimension"] == "time"
            assert row["scope_key"] != "global"
            assert scope_matches(migrated_scope, {}) is False
            context_id = migrated_scope["all_of"][0]["context_id"]
            catalog_row = connection.execute(
                """
                SELECT label,
                       (SELECT COUNT(*) FROM memory_context_aliases
                        WHERE context_id = catalog.context_id) AS alias_count
                FROM memory_context_catalog AS catalog
                WHERE context_id = ?
                """,
                (context_id,),
            ).fetchone()
            assert catalog_row["label"] == ""
            assert catalog_row["alias_count"] == 0

        orphan = connection.execute(
            """
            SELECT label,
                   (SELECT COUNT(*) FROM memory_context_aliases
                    WHERE context_id = catalog.context_id) AS alias_count
            FROM memory_context_catalog AS catalog
            WHERE context_id = ?
            """,
            (orphan_context_id,),
        ).fetchone()
        assert orphan["label"] == ""
        assert orphan["alias_count"] == 0
        visible_context_text = "\n".join(
            str(row[0])
            for row in connection.execute(
                """
                SELECT label FROM memory_context_catalog
                UNION ALL
                SELECT alias FROM memory_context_aliases
                """
            )
        )
        assert "unexpected-secret" not in visible_context_text
        assert "broken-secret" not in visible_context_text
        collision_rows = connection.execute(
            """
            SELECT status, scope_json
            FROM tom_trait_assertions
            WHERE slot_key = 'quarantine-collision-slot'
            ORDER BY assertion_id
            """
        ).fetchall()
        assert [row["status"] for row in collision_rows] == ["active", "active"]
        assert len({row["scope_json"] for row in collision_rows}) == 2


def test_v13_scope_collision_preserves_authoritative_and_valid_assertions(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v12_scheduled_correction_transitions")

    with sqlite3.connect(db_path) as connection:
        _insert_assertion(
            connection,
            assertion_id="confirmed-old",
            slot_key="confirmed-slot",
            value="User confirmed",
            scope={"activity": "coding"},
            user_feedback="confirmed",
        )
        _insert_assertion(
            connection,
            assertion_id="tentative-new",
            slot_key="confirmed-slot",
            value="New inference",
            scope={"activity": "code"},
            validation_state="tentative",
            created_at=40,
            updated_at=50,
            valid_from=40,
        )
        _insert_assertion(
            connection,
            assertion_id="authored-old",
            slot_key="authored-slot",
            value="User authored",
            scope={"activity": "coding"},
            source_domain="user_authored",
        )
        _insert_assertion(
            connection,
            assertion_id="inferred-new",
            slot_key="authored-slot",
            value="New inference",
            scope={"activity": "code"},
            created_at=40,
            updated_at=50,
            valid_from=40,
        )
        _insert_assertion(
            connection,
            assertion_id="stable-old",
            slot_key="validity-slot",
            value="Stable",
            scope={"activity": "coding"},
        )
        _insert_assertion(
            connection,
            assertion_id="invalid-new",
            slot_key="validity-slot",
            value="Invalid",
            scope={"activity": "code"},
            validation_state="contradicted",
            status="invalidated",
            created_at=40,
            updated_at=50,
            valid_from=40,
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = {
            str(row["assertion_id"]): dict(row)
            for row in connection.execute(
                """
                SELECT assertion_id, status, superseded_by, valid_from, valid_to
                FROM tom_trait_assertions
                WHERE slot_key IN ('confirmed-slot', 'authored-slot', 'validity-slot')
                """
            )
        }

    assert rows["confirmed-old"]["status"] == "active"
    assert rows["tentative-new"]["superseded_by"] == "confirmed-old"
    assert rows["tentative-new"]["valid_to"] >= rows["tentative-new"]["valid_from"]
    assert rows["authored-old"]["status"] == "active"
    assert rows["inferred-new"]["superseded_by"] == "authored-old"
    assert rows["stable-old"]["status"] == "active"
    assert rows["invalid-new"]["superseded_by"] == "stable-old"


@pytest.mark.parametrize(
    ("target_kind", "malformed_field", "before", "replacement"),
    [
        (
            "assertion",
            "before_json",
            {},
            None,
        ),
        (
            "assertion",
            "replacement_json",
            {"trait_value": "Hangzhou", "scope_json": "{}"},
            {"scope": {}},
        ),
        (
            "edge",
            "before_json",
            {"subject_id": "user:u1", "predicate": "LIVES_IN"},
            None,
        ),
        (
            "edge",
            "replacement_json",
            {
                "subject_id": "user:u1",
                "predicate": "LIVES_IN",
                "object_id": "place:hangzhou",
                "scope_json": "{}",
            },
            {"subject_id": "user:u1", "object_id": "place:shanghai"},
        ),
        (
            "assertion",
            "before_json.scope_json",
            {"trait_value": "Hangzhou", "scope_json": None},
            None,
        ),
    ],
)
def test_v13_refuses_semantically_incomplete_correction_snapshots(
    tmp_path: Path,
    target_kind: str,
    malformed_field: str,
    before: dict,
    replacement: dict | None,
) -> None:
    db_path = tmp_path / f"{target_kind}-{malformed_field.replace('.', '-')}.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v12_scheduled_correction_transitions")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                replacement_json, state, created_at
            ) VALUES (
                'correction-incomplete', 'request-incomplete', 'user:u1', ?,
                'target-1', 'slot-1', 'claim-still-active', 'record_error',
                ?, ?, 'active', 30
            )
            """,
            (
                target_kind,
                json.dumps(before),
                json.dumps(replacement) if replacement is not None else None,
            ),
        )
        connection.execute(
            """
            INSERT INTO memory_correction_rules(
                rule_id, correction_id, target_kind, rule_kind, slot_key,
                claim_fingerprint, scope_key, active, created_at
            ) VALUES (
                'rule-incomplete', 'correction-incomplete', ?, 'block_claim',
                'slot-1', 'claim-still-active', 'global', 1, 30
            )
            """,
            (target_kind,),
        )
        connection.commit()

    with pytest.raises(ValueError, match=malformed_field.split(".")[0]):
        command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT claim_fingerprint, scope_key, active
            FROM memory_correction_rules WHERE rule_id = 'rule-incomplete'
            """
        ).fetchone() == ("claim-still-active", "global", 1)


def test_v13_normalizes_v4_global_correction_scope_for_history_models(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "memory.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v3_experience_draft_cover")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO tom_trait_assertions(
                assertion_id, entity_id, entity_type, trait_family, trait_name,
                trait_value, confidence_score, evidence_events, volatility_index,
                source_domain, inference_depth, validation_state, first_inferred_at,
                last_validated_at, status, created_at, updated_at
            ) VALUES (
                'rejected-v3', 'user:u1', 'user', 'identity_profile',
                'location.home', 'Hangzhou', 0.9, '["event-1"]', 0.1,
                'chat', 'explicit', 'user_rejected', 10, 20,
                'user_rejected', 10, 20
            )
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT * FROM memory_corrections
            WHERE target_kind = 'assertion' AND target_id = 'rejected-v3'
            """
        ).fetchone()
        assert row is not None
        assert row["scope_json"] is None
        correction = MemoryCorrection.from_row(dict(row))

    record = MemoryCorrectionRecord.model_validate(asdict(correction))
    assert record.scope is None


@pytest.mark.parametrize("invalid_scope", [[], "", 0, False])
@pytest.mark.parametrize("snapshot_field", ["before_json", "replacement_json"])
def test_v13_quarantines_explicit_invalid_correction_snapshot_scopes(
    tmp_path: Path,
    invalid_scope: object,
    snapshot_field: str,
) -> None:
    db_path = tmp_path / f"{snapshot_field}-{type(invalid_scope).__name__}.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v12_scheduled_correction_transitions")
    before = {"trait_value": "Hangzhou", "scope": {}}
    replacement = {"value": "Shanghai", "scope": {}}
    if snapshot_field == "before_json":
        before["scope"] = invalid_scope
    else:
        replacement["scope"] = invalid_scope
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                replacement_json, state, created_at
            ) VALUES (
                'correction-invalid-scope', 'request-invalid-scope', 'user:u1',
                'assertion', 'assertion-1', 'slot-1', 'legacy-claim',
                'scope_refinement', ?, ?, 'active', 30
            )
            """,
            (json.dumps(before), json.dumps(replacement)),
        )
        connection.execute(
            """
            INSERT INTO memory_correction_rules(
                rule_id, correction_id, target_kind, rule_kind, slot_key,
                claim_fingerprint, scope_key, active, created_at
            ) VALUES (
                'rule-invalid-scope', 'correction-invalid-scope', 'assertion',
                ?, 'slot-1', 'legacy-claim', 'global', 1, 30
            )
            """,
            ("block_claim" if snapshot_field == "before_json" else "authoritative_slot",),
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        correction = connection.execute(
            "SELECT * FROM memory_corrections WHERE correction_id = 'correction-invalid-scope'"
        ).fetchone()
        rule = connection.execute(
            "SELECT scope_key FROM memory_correction_rules WHERE rule_id = 'rule-invalid-scope'"
        ).fetchone()
    migrated_snapshot = json.loads(correction[snapshot_field])
    assert migrated_snapshot["scope"]["all_of"][0]["dimension"] == "time"
    assert rule["scope_key"] != "global"


@pytest.mark.parametrize("malformed_field", ["before_json", "replacement_json"])
def test_v13_refuses_to_disable_rules_when_correction_snapshots_are_malformed(
    tmp_path: Path,
    malformed_field: str,
) -> None:
    db_path = tmp_path / f"{malformed_field}.db"
    config = _memory_config(db_path)
    command.upgrade(config, "v12_scheduled_correction_transitions")
    valid_before = json.dumps(
        {
            "slot_key": "slot-1",
            "trait_value": "Hangzhou",
            "scope_json": "{}",
        }
    )
    before_json = "{broken" if malformed_field == "before_json" else valid_before
    replacement_json = (
        "{broken"
        if malformed_field == "replacement_json"
        else json.dumps({"value": "Shanghai", "scope": {}})
    )

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                replacement_json, state, created_at
            ) VALUES (
                'correction-malformed', 'request-malformed', 'user:u1',
                'assertion', 'assertion-1', 'slot-1', 'claim-still-active',
                'record_error', ?, ?, 'active', 30
            )
            """,
            (before_json, replacement_json),
        )
        connection.execute(
            """
            INSERT INTO memory_correction_rules(
                rule_id, correction_id, target_kind, rule_kind, slot_key,
                claim_fingerprint, scope_key, active, created_at
            ) VALUES (
                'rule-malformed', 'correction-malformed', 'assertion',
                'block_claim', 'slot-1', 'claim-still-active', 'global', 1, 30
            )
            """
        )
        connection.commit()

    with pytest.raises(ValueError, match=malformed_field):
        command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "v12_scheduled_correction_transitions",
        )
        assert connection.execute(
            """
            SELECT claim_fingerprint, scope_key, active
            FROM memory_correction_rules WHERE rule_id = 'rule-malformed'
            """
        ).fetchone() == ("claim-still-active", "global", 1)
