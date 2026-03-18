from __future__ import annotations

import sqlite3

import pytest


def test_default_identity_resolver_maps_web_runtime_to_self():
    from magi.memory.identity_resolver import IdentityResolver

    resolver = IdentityResolver.in_memory_default()

    result = resolver.resolve_memory_owner_id(runtime_user_id="web_user", source="chat")

    assert result == "user:self"


def test_identity_resolver_allows_multiple_runtime_accounts_for_same_self():
    from magi.memory.identity_resolver import IdentityResolver

    resolver = IdentityResolver.in_memory_default(
        links=[
            ("web", "web_user", "user:self"),
            ("telegram", "asuka_main", "user:self"),
        ]
    )

    assert resolver.resolve_memory_owner_id(runtime_user_id="web_user", source="web") == "user:self"
    assert resolver.resolve_memory_owner_id(runtime_user_id="asuka_main", source="telegram") == "user:self"


@pytest.mark.asyncio
async def test_identity_links_persist_across_store_instances(tmp_path):
    from magi.memory.identity_resolver import IdentityResolver

    db_path = tmp_path / "identity_links.db"

    resolver = IdentityResolver(db_path=str(db_path))
    await resolver.initialize()
    try:
        await resolver.upsert_identity_link(
            namespace="telegram",
            runtime_user_id="asuka_main",
            memory_owner_id="user:self",
        )
    finally:
        await resolver.shutdown()

    reopened = IdentityResolver(db_path=str(db_path))
    await reopened.initialize()
    try:
        links = await reopened.list_identity_links()

        assert reopened.resolve_memory_owner_id(runtime_user_id="asuka_main", source="telegram") == "user:self"
        assert len(links) == 1
        assert links[0].namespace == "telegram"
        assert links[0].runtime_user_id == "asuka_main"
        assert links[0].memory_owner_id == "user:self"
    finally:
        await reopened.shutdown()


@pytest.mark.asyncio
async def test_identity_migration_rewrites_legacy_web_user_refs(tmp_path):
    from magi.memory.identity_migration import migrate_legacy_self_identity
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l2_cognition_store import L2CognitionStore

    l1_db_path = tmp_path / "l1_events.db"
    memory_db_path = tmp_path / "memory.db"

    l1_store = L1EventStore(db_path=str(l1_db_path), vector_enabled=False)
    l2_store = L2CognitionStore(db_path=str(memory_db_path))
    await l1_store.initialize()
    await l2_store.initialize()

    l1_conn = sqlite3.connect(str(l1_db_path))
    l1_conn.execute(
        """
        INSERT INTO fact_events (
            event_id, correlation_id, parent_event_id, timestamp, created_at,
            event_type, source, source_item_id, memory_domain, ingest_target,
            cognition_eligible, tom_depth, retention_class, session_id, user_id, runtime_user_id, memory_owner_id,
            task_id, goal_id, raw_content, structured_payload, metadata,
            importance_score, importance_t0_base, importance_t1_score, importance_version,
            level, media_path, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "evt-legacy-1",
            "corr-legacy-1",
            None,
            1.0,
            1.0,
            "UserMessage",
            "chat",
            None,
            1,
            2,
            1,
            3,
            3,
            "s1",
            "web_user",
            "web_user",
            "user:web_user",
            None,
            None,
            "legacy event",
            "{}",
            "{}",
            0.8,
            0.8,
            None,
            1,
            1,
            None,
            None,
        ),
    )
    l1_conn.commit()
    l1_conn.close()

    memory_conn = sqlite3.connect(str(memory_db_path))
    memory_conn.execute(
        """
        INSERT INTO knowledge_graph (
            triple_id, subject_id, subject_type, predicate, object_id, object_type,
            confidence, evidence_event_ids, observation_count, first_observed_at,
            last_observed_at, last_confirmed_at, source_type, extraction_method,
            status, deprecated_by, deprecated_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "triple-legacy-1",
            "user:web_user",
            "user",
            "LIKES",
            "food:sushi",
            "food",
            0.8,
            "[\"evt-legacy-1\"]",
            1,
            1.0,
            1.0,
            1.0,
            "chat",
            "legacy",
            "active",
            None,
            None,
            1.0,
            1.0,
        ),
    )
    memory_conn.execute(
        """
        INSERT INTO tom_trait_assertions (
            assertion_id, entity_id, entity_type, trait_name, trait_value,
            confidence_score, evidence_events, volatility_index, source_domain,
            inference_depth, validation_state, first_inferred_at,
            last_validated_at, expires_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "assert-legacy-1",
            "user:web_user",
            "user",
            "stress_level",
            "high",
            0.7,
            "[\"evt-legacy-1\"]",
            0.7,
            "user_authored",
            "defensive_psychology",
            "tentative",
            1.0,
            1.0,
            None,
            1.0,
            1.0,
        ),
    )
    memory_conn.execute(
        """
        INSERT INTO tom_snapshots (
            snapshot_id, entity_id, entity_type, core_traits, sensitive_triggers,
            preferences, public_sentiment_profile, relationship_topology,
            current_stress_level, current_mood, current_engagement, current_context,
            interaction_count, last_interaction_at, last_updated_at,
            update_source_assertion_ids, snapshot_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "snapshot-legacy-1",
            "user:web_user",
            "user",
            "{}",
            "[]",
            "{}",
            "{}",
            "{}",
            0.0,
            None,
            0.5,
            "{}",
            0,
            None,
            1.0,
            "[]",
            1,
            1.0,
        ),
    )
    memory_conn.commit()
    memory_conn.close()

    result = await migrate_legacy_self_identity(
        l1_db_path=str(l1_db_path),
        memory_db_path=str(memory_db_path),
    )

    assert result["l1_fact_events_updated"] == 1
    assert result["knowledge_graph_updated"] == 1
    assert result["assertions_updated"] == 1
    assert result["snapshots_updated"] == 1

    l1_verify = sqlite3.connect(str(l1_db_path))
    l1_row = l1_verify.execute(
        "SELECT runtime_user_id, memory_owner_id FROM fact_events WHERE event_id = ?",
        ("evt-legacy-1",),
    ).fetchone()
    l1_verify.close()

    memory_verify = sqlite3.connect(str(memory_db_path))
    graph_row = memory_verify.execute(
        "SELECT subject_id FROM knowledge_graph WHERE triple_id = ?",
        ("triple-legacy-1",),
    ).fetchone()
    assertion_row = memory_verify.execute(
        "SELECT entity_id FROM tom_trait_assertions WHERE assertion_id = ?",
        ("assert-legacy-1",),
    ).fetchone()
    snapshot_row = memory_verify.execute(
        "SELECT entity_id FROM tom_snapshots WHERE snapshot_id = ?",
        ("snapshot-legacy-1",),
    ).fetchone()
    legacy_count = memory_verify.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM knowledge_graph WHERE subject_id = 'user:web_user' OR object_id = 'user:web_user')
            + (SELECT COUNT(*) FROM tom_trait_assertions WHERE entity_id = 'user:web_user')
            + (SELECT COUNT(*) FROM tom_snapshots WHERE entity_id = 'user:web_user')
        """
    ).fetchone()[0]
    memory_verify.close()

    assert l1_row == ("web_user", "user:self")
    assert graph_row == ("user:self",)
    assert assertion_row == ("user:self",)
    assert snapshot_row == ("user:self",)
    assert legacy_count == 0


@pytest.mark.asyncio
async def test_unified_memory_store_initialization_runs_legacy_self_migration(tmp_path):
    from magi.memory import UnifiedMemoryStore
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l2_cognition_store import L2CognitionStore

    l1_db_path = tmp_path / "l1_events.db"
    memory_db_path = tmp_path / "memory.db"

    l1_store = L1EventStore(db_path=str(l1_db_path), vector_enabled=False)
    l2_store = L2CognitionStore(db_path=str(memory_db_path))
    await l1_store.initialize()
    await l2_store.initialize()

    l1_conn = sqlite3.connect(str(l1_db_path))
    l1_conn.execute(
        """
        INSERT INTO fact_events (
            event_id, correlation_id, parent_event_id, timestamp, created_at,
            event_type, source, source_item_id, memory_domain, ingest_target,
            cognition_eligible, tom_depth, retention_class, session_id, user_id, runtime_user_id, memory_owner_id,
            task_id, goal_id, raw_content, structured_payload, metadata,
            importance_score, importance_t0_base, importance_t1_score, importance_version,
            level, media_path, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "evt-legacy-init-1",
            "corr-legacy-init-1",
            None,
            1.0,
            1.0,
            "UserMessage",
            "chat",
            None,
            1,
            2,
            1,
            3,
            3,
            "s1",
            "web_user",
            "web_user",
            "user:web_user",
            None,
            None,
            "legacy event",
            "{}",
            "{}",
            0.8,
            0.8,
            None,
            1,
            1,
            None,
            None,
        ),
    )
    l1_conn.commit()
    l1_conn.close()

    memory_conn = sqlite3.connect(str(memory_db_path))
    memory_conn.execute(
        """
        INSERT INTO tom_trait_assertions (
            assertion_id, entity_id, entity_type, trait_name, trait_value,
            confidence_score, evidence_events, volatility_index, source_domain,
            inference_depth, validation_state, first_inferred_at,
            last_validated_at, expires_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "assert-legacy-init-1",
            "user:web_user",
            "user",
            "stress_level",
            "high",
            0.7,
            "[\"evt-legacy-init-1\"]",
            0.7,
            "user_authored",
            "defensive_psychology",
            "tentative",
            1.0,
            1.0,
            None,
            1.0,
            1.0,
        ),
    )
    memory_conn.commit()
    memory_conn.close()

    unified = UnifiedMemoryStore(
        l1_db_path=str(l1_db_path),
        memory_db_path=str(memory_db_path),
        enable_l0=False,
        enable_l3=False,
        enable_l4=False,
    )
    await unified.initialize()
    try:
        restored_event = await unified.l1.get_memory_event("evt-legacy-init-1") if unified.l1 is not None else None
        assertions = await unified.l2.list_tom_assertions(entity_id="user:self") if unified.l2 is not None else []

        assert restored_event is not None
        assert restored_event.memory_owner_id == "user:self"
        assert len(assertions) == 1
        assert assertions[0]["entity_id"] == "user:self"
    finally:
        await unified.shutdown()
