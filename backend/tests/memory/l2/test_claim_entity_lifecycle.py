"""Grounded Claim lifecycle coverage for entity merge and forget."""

from __future__ import annotations

import json

import aiosqlite
import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.claims.reprojection import reproject_stale_claim_routes
from magi.memory.l2.claims.identity import projection_outcome_id
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.entities.maintenance import L2EntityMaintenance
from magi.memory.l2.semantic_routing import (
    ROUTE_CONTRACT_VERSION,
    SemanticRouteInput,
    derive_semantic_route,
)
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder

pytestmark = pytest.mark.asyncio


def _claim_event_id(claim_id: str) -> str:
    return f"evt-{claim_id}"


def _claim_route(*, claim_id: str, object_entity_id: str):  # type: ignore[no-untyped-def]
    return derive_semantic_route(
        SemanticRouteInput(
            claim_id=claim_id,
            subject_id="user:u1",
            subject_type="user",
            canonical_predicate="LIKES",
            fact_kind="stable_preference",
            object_type="topic",
            object_value="Jazz",
            object_entity_id=object_entity_id,
            temporal_cue="recurring",
            specificity="concrete",
            target_from=None,
            target_to=None,
            raw_time_expression="",
            time_resolution="unscheduled",
        )
    )


def _route_details(route) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return {
        "semantic_route_id": route.semantic_route_id,
        "family": route.family,
        "trait_code": route.trait_code,
        "object_role": route.object_role.value,
        "value_fingerprint": route.value_fingerprint,
        "target_entity_type": route.target_entity_type,
        "target_window_key": route.target_window_key,
        "scope_key": route.scope_key,
    }


async def _seed_claim(
    store,  # type: ignore[no-untyped-def]
    *,
    claim_id: str,
    object_entity_id: str,
) -> None:
    route = _claim_route(claim_id=claim_id, object_entity_id=object_entity_id)
    assert route.route_key is not None
    assert route.slot_key is not None
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO l2_grounded_claims(
                claim_id, identity_key, extractor_contract_version,
                evidence_rule_version, origin_attempt_key, profile_id, user_id,
                subject_ref, subject_type, canonical_predicate, fact_kind,
                object_type, polarity, specificity, confidence,
                object_value_json, object_surface, temporal_cue, availability,
                created_at, updated_at
            ) VALUES (?, ?, 2, 1, 'attempt:seed', 'chat.user_message', 'u1',
                      'user:u1', 'user', 'LIKES', 'stable_preference', 'topic',
                      'positive', 'concrete', 0.9, ?, 'Jazz', 'recurring',
                      'active', 10.0, 10.0)
            """,
            (claim_id, f"identity:{claim_id}", json.dumps("Jazz")),
        )
        await db.execute(
            """
            INSERT INTO l2_claim_evidence(
                claim_id, event_id, link_role, required_for_grounding,
                event_time, timestamp_confidence, timestamp_quality,
                evidence_rule_version, evidence_mode, source_type,
                source_domain, author_type, evidence_class, created_at
            ) VALUES (?, ?, 'supporting', 1, 10.0, 'exact', 'exact', 1,
                      'direct', 'chat', 'user_authored', 'user',
                      'user_self_report', 10.0)
            """,
            (claim_id, _claim_event_id(claim_id)),
        )
        await db.execute(
            """
            INSERT INTO l2_claim_entity_refs(
                claim_id, ref_role, entity_id, resolution_version, created_at
            ) VALUES (?, 'object', ?, 1, 10.0)
            """,
            (claim_id, object_entity_id),
        )
        await db.execute(
            """
            INSERT INTO l2_claim_projection_outcomes(
                outcome_id, claim_id, attempt_key, target_kind, target_id,
                target_slot_key, route_contract_version, outcome, reason_code,
                details_json, created_at
            ) VALUES (?, ?, 'attempt:seed', 'route', ?,
                      ?, ?, 'routed', 'seed', ?, 10.0)
            """,
            (
                f"outcome:{claim_id}:current",
                claim_id,
                route.route_key,
                route.slot_key,
                ROUTE_CONTRACT_VERSION,
                json.dumps(_route_details(route)),
            ),
        )
        await db.execute(
            """
            INSERT INTO l2_claim_projection_outcomes(
                outcome_id, claim_id, attempt_key, target_kind, target_id,
                target_slot_key, route_contract_version, outcome, reason_code,
                details_json, created_at, invalidated_at, invalidated_reason
            ) VALUES (?, ?, 'attempt:old', 'assertion', 'assertion:sensitive',
                      'slot:sensitive', ?, 'projected', 'seed', ?, 9.0, 9.5,
                      'superseded')
            """,
            (
                f"outcome:{claim_id}:historical",
                claim_id,
                ROUTE_CONTRACT_VERSION,
                json.dumps({"natural_summary": "User likes Jazz"}),
            ),
        )
        await db.commit()


async def _seed_claim_target(
    store,  # type: ignore[no-untyped-def]
    *,
    claim_id: str,
    object_entity_id: str,
    target_kind: str,
    authority_ref: str | None = None,
    extra_evidence_event_ids: tuple[str, ...] = (),
) -> str:
    route = _claim_route(claim_id=claim_id, object_entity_id=object_entity_id)
    assert route.slot_key is not None
    evidence_event_ids = [_claim_event_id(claim_id), *extra_evidence_event_ids]
    if target_kind == "assertion":
        target_id = await store.upsert_assertion_candidate(
            {
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "preference_profile",
                "trait_name": "preference.affinity",
                "trait_value": "like",
                "confidence_score": 0.9,
                "evidence_events": evidence_event_ids,
                "volatility_index": 0.05,
                "source_domain": "conversation",
                "inference_depth": "explicit",
                "validation_state": "tentative",
                "first_inferred_at": 10.0,
                "last_validated_at": 10.0,
                "target_entity_id": object_entity_id,
                "target_entity_type": "topic",
                "temporal_scope": "persistent",
                "semantic_route_slot_key": route.slot_key,
            }
        )
        table = "tom_trait_assertions"
        id_column = "assertion_id"
    elif target_kind == "relationship":
        target_id = await store.upsert_knowledge_edge(
            subject_id="user:u1",
            subject_type="user",
            predicate="LIKES",
            object_id=object_entity_id,
            object_type="topic",
            fact_kind="stable_preference",
            evidence_event_ids=evidence_event_ids,
            confidence=0.9,
            observed_at=10.0,
            source_type="conversation",
            extraction_method="llm_phase1_grounded",
        )
        table = "knowledge_graph"
        id_column = "triple_id"
    else:
        raise ValueError(f"unsupported target kind: {target_kind}")

    async with sqlite_connection_async(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        if authority_ref is not None:
            await db.execute(
                f"UPDATE {table} SET authority_ref = ? WHERE {id_column} = ?",
                (authority_ref, target_id),
            )
        async with db.execute(
            f"SELECT slot_key FROM {table} WHERE {id_column} = ?",
            (target_id,),
        ) as cursor:
            target = await cursor.fetchone()
        assert target is not None
        outcome_id = projection_outcome_id(
            claim_id=claim_id,
            attempt_key="attempt:seed",
            target_kind=target_kind,
            target_id=target_id,
        )
        await db.execute(
            """
            INSERT INTO l2_claim_projection_outcomes(
                outcome_id, claim_id, attempt_key, target_kind, target_id,
                target_slot_key, route_contract_version, outcome, reason_code,
                created_at
            ) VALUES (?, ?, 'attempt:seed', ?, ?, ?, ?, 'projected', 'seed', 11.0)
            """,
            (
                outcome_id,
                claim_id,
                target_kind,
                target_id,
                str(target["slot_key"]),
                ROUTE_CONTRACT_VERSION,
            ),
        )
        await db.commit()
    return str(target_id)


async def _target_row_for_entity(
    store,  # type: ignore[no-untyped-def]
    *,
    target_kind: str,
    entity_id: str,
) -> dict[str, object]:
    if target_kind == "assertion":
        query = """
            SELECT assertion_id AS target_id, status, target_entity_id,
                   evidence_events AS evidence_json, authority_ref
            FROM tom_trait_assertions
            WHERE target_entity_id = ?
            ORDER BY updated_at DESC, assertion_id
            LIMIT 1
        """
    else:
        query = """
            SELECT triple_id AS target_id, status, object_id AS target_entity_id,
                   evidence_event_ids AS evidence_json, authority_ref
            FROM knowledge_graph
            WHERE object_id = ?
            ORDER BY updated_at DESC, triple_id
            LIMIT 1
        """
    async with sqlite_connection_async(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, (entity_id,)) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    return dict(row)


async def _attach_claim_to_target(
    store,  # type: ignore[no-untyped-def]
    *,
    claim_id: str,
    target_kind: str,
    target_id: str,
) -> None:
    if target_kind == "assertion":
        table = "tom_trait_assertions"
        id_column = "assertion_id"
        evidence_column = "evidence_events"
    else:
        table = "knowledge_graph"
        id_column = "triple_id"
        evidence_column = "evidence_event_ids"
    async with sqlite_connection_async(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT slot_key, {evidence_column} FROM {table} WHERE {id_column} = ?",
            (target_id,),
        ) as cursor:
            target = await cursor.fetchone()
        assert target is not None
        evidence = sorted(
            {
                *json.loads(str(target[evidence_column] or "[]")),
                _claim_event_id(claim_id),
            }
        )
        await db.execute(
            f"UPDATE {table} SET {evidence_column} = ? WHERE {id_column} = ?",
            (json.dumps(evidence), target_id),
        )
        await db.execute(
            """
            INSERT INTO l2_claim_projection_outcomes(
                outcome_id, claim_id, attempt_key, target_kind, target_id,
                target_slot_key, route_contract_version, outcome, reason_code,
                created_at
            ) VALUES (?, ?, 'attempt:seed', ?, ?, ?, ?, 'projected', 'seed', 11.0)
            """,
            (
                projection_outcome_id(
                    claim_id=claim_id,
                    attempt_key="attempt:seed",
                    target_kind=target_kind,
                    target_id=target_id,
                ),
                claim_id,
                target_kind,
                target_id,
                str(target["slot_key"]),
                ROUTE_CONTRACT_VERSION,
            ),
        )
        await db.commit()


async def _claim_rows(store, claim_id: str):  # type: ignore[no-untyped-def]
    async with sqlite_connection_async(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM l2_grounded_claims WHERE claim_id = ?",
            (claim_id,),
        ) as cursor:
            claim = dict(await cursor.fetchone())
        async with db.execute(
            """
            SELECT * FROM l2_claim_entity_refs
            WHERE claim_id = ? ORDER BY resolution_version
            """,
            (claim_id,),
        ) as cursor:
            refs = [dict(row) for row in await cursor.fetchall()]
        async with db.execute(
            """
            SELECT * FROM l2_claim_projection_outcomes
            WHERE claim_id = ? ORDER BY created_at, outcome_id
            """,
            (claim_id,),
        ) as cursor:
            outcomes = [dict(row) for row in await cursor.fetchall()]
        async with db.execute(
            "SELECT COUNT(*) FROM l2_claim_evidence WHERE claim_id = ?",
            (claim_id,),
        ) as cursor:
            evidence_count = int((await cursor.fetchone())[0])
    return claim, refs, outcomes, evidence_count


async def test_entity_merge_rekeys_claim_ref_and_reprojects_route(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    for entity_id in ("topic:winner", "topic:loser"):
        await catalog.upsert_entity(
            entity_id=entity_id,
            canonical_name="Jazz",
            entity_type="topic",
        )
    await _seed_claim(
        store,
        claim_id="claim:merge",
        object_entity_id="topic:loser",
    )

    await L2EntityMaintenance(db_path=store.db_path)._merge_entity_into(
        "topic:winner",
        "topic:loser",
    )

    _claim, refs, outcomes, _evidence_count = await _claim_rows(store, "claim:merge")
    assert [
        (row["entity_id"], row["resolution_version"], row["invalidated_reason"]) for row in refs
    ] == [
        ("topic:loser", 1, "entity_merged"),
        ("topic:winner", 2, None),
    ]
    assert outcomes[-1]["invalidated_reason"] == "entity_merged"

    stats = await reproject_stale_claim_routes(store)
    assert stats.outcomes_appended == 1
    _claim, _refs, outcomes, _evidence_count = await _claim_rows(store, "claim:merge")
    current_route = next(
        row
        for row in reversed(outcomes)
        if row["target_kind"] == "route" and row["invalidated_at"] is None
    )
    expected = derive_semantic_route(
        SemanticRouteInput(
            claim_id="claim:merge",
            subject_id="user:u1",
            subject_type="user",
            canonical_predicate="LIKES",
            fact_kind="stable_preference",
            object_type="topic",
            object_value="Jazz",
            object_entity_id="topic:winner",
            temporal_cue="recurring",
            specificity="concrete",
            target_from=None,
            target_to=None,
            raw_time_expression="",
            time_resolution="unscheduled",
        )
    )
    assert current_route["target_id"] == expected.route_key
    assert current_route["attempt_key"] == (
        f"route-reproject:v{ROUTE_CONTRACT_VERSION}:r2:claim:merge"
    )


async def test_entity_forget_irreversibly_redacts_claim_and_all_outcome_history(
    l2_store_with_schema,
) -> None:
    store = l2_store_with_schema
    await _seed_claim(
        store,
        claim_id="claim:forget",
        object_entity_id="topic:private",
    )

    counts = await store.forget_entity(entity_id="topic:private")

    assert counts["l2_grounded_claims"] == 1
    assert counts["l2_claim_evidence"] == 1
    assert counts["l2_claim_entity_refs"] == 1
    assert counts["l2_claim_projection_outcomes"] == 2
    claim, refs, outcomes, evidence_count = await _claim_rows(store, "claim:forget")
    assert claim["availability"] == "forgotten"
    assert claim["identity_key"] == "identity:claim:forget"
    assert claim["forget_tombstone_key"]
    assert claim["subject_ref"] is None
    assert claim["object_surface"] is None
    assert refs == []
    assert evidence_count == 0
    assert all(str(row["target_id"]).startswith("redacted:") for row in outcomes)
    assert all(row["details_json"] is None for row in outcomes)
    assert all(row["invalidated_at"] is not None for row in outcomes)

    repeated = await store.forget_entity(entity_id="topic:private")
    assert repeated["l2_grounded_claims"] == 0
    assert repeated["l2_claim_projection_outcomes"] == 0


@pytest.mark.parametrize("target_kind", ["assertion", "relationship"])
@pytest.mark.parametrize("operation_order", ["merge_then_forget", "forget_then_merge"])
async def test_entity_merge_and_forget_converge_without_claim_target_leaks(
    l2_store_with_schema,
    target_kind: str,
    operation_order: str,
) -> None:
    store = l2_store_with_schema
    winner_id = "topic:winner"
    loser_id = "topic:loser"
    claim_id = f"claim:{target_kind}:{operation_order}"
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    for entity_id in (winner_id, loser_id):
        await catalog.upsert_entity(
            entity_id=entity_id,
            canonical_name="Jazz",
            entity_type="topic",
        )
    await _seed_claim(store, claim_id=claim_id, object_entity_id=loser_id)
    await _seed_claim_target(
        store,
        claim_id=claim_id,
        object_entity_id=loser_id,
        target_kind=target_kind,
    )

    maintenance = L2EntityMaintenance(db_path=store.db_path)
    if operation_order == "merge_then_forget":
        await maintenance._merge_entity_into(winner_id, loser_id)
        await store.forget_entity(entity_id=loser_id)
    else:
        await store.forget_entity(entity_id=loser_id)
        await maintenance._merge_entity_into(winner_id, loser_id)

    claim, refs, outcomes, evidence_count = await _claim_rows(store, claim_id)
    target = await _target_row_for_entity(
        store,
        target_kind=target_kind,
        entity_id=winner_id,
    )
    assert claim["availability"] == "forgotten"
    assert refs == []
    assert evidence_count == 0
    assert all(str(row["target_id"]).startswith("redacted:") for row in outcomes)
    assert target["target_entity_id"] == winner_id
    assert target["status"] == "archived"
    if target_kind == "assertion":
        assert await store.list_current_assertions(entity_id="user:u1") == []
        portrait = await UserPortraitProjectionBuilder(store).build("u1")
        assert f"assertion:{target['target_id']}" not in portrait.evidence_refs
    else:
        assert await store.list_current_relationships(subject_id="user:u1") == []


@pytest.mark.parametrize("target_kind", ["assertion", "relationship"])
async def test_forget_merged_entity_preserves_other_claim_support(
    l2_store_with_schema,
    target_kind: str,
) -> None:
    store = l2_store_with_schema
    winner_id = "topic:winner"
    loser_id = "topic:loser"
    forgotten_claim_id = f"claim:{target_kind}:forgotten"
    surviving_claim_id = f"claim:{target_kind}:surviving"
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    for entity_id in (winner_id, loser_id):
        await catalog.upsert_entity(
            entity_id=entity_id,
            canonical_name="Jazz",
            entity_type="topic",
        )
    await _seed_claim(
        store,
        claim_id=forgotten_claim_id,
        object_entity_id=loser_id,
    )
    await _seed_claim_target(
        store,
        claim_id=forgotten_claim_id,
        object_entity_id=loser_id,
        target_kind=target_kind,
    )
    await L2EntityMaintenance(db_path=store.db_path)._merge_entity_into(
        winner_id,
        loser_id,
    )
    canonical_target = await _target_row_for_entity(
        store,
        target_kind=target_kind,
        entity_id=winner_id,
    )
    await _seed_claim(
        store,
        claim_id=surviving_claim_id,
        object_entity_id=winner_id,
    )
    await _attach_claim_to_target(
        store,
        claim_id=surviving_claim_id,
        target_kind=target_kind,
        target_id=str(canonical_target["target_id"]),
    )

    await store.forget_entity(entity_id=loser_id)

    forgotten_claim, _refs, _outcomes, _evidence_count = await _claim_rows(
        store,
        forgotten_claim_id,
    )
    surviving_claim, _refs, _outcomes, surviving_evidence_count = await _claim_rows(
        store,
        surviving_claim_id,
    )
    target = await _target_row_for_entity(
        store,
        target_kind=target_kind,
        entity_id=winner_id,
    )
    assert forgotten_claim["availability"] == "forgotten"
    assert surviving_claim["availability"] == "active"
    assert surviving_evidence_count == 1
    assert target["status"] != "archived"
    assert json.loads(str(target["evidence_json"])) == [_claim_event_id(surviving_claim_id)]


@pytest.mark.parametrize("target_kind", ["assertion", "relationship"])
async def test_forget_merged_entity_preserves_independent_target_authority(
    l2_store_with_schema,
    target_kind: str,
) -> None:
    store = l2_store_with_schema
    winner_id = "topic:winner"
    loser_id = "topic:loser"
    claim_id = f"claim:{target_kind}:authority"
    catalog = L2EntityCatalog(db_path=store.db_path, vector_enabled=False)
    for entity_id in (winner_id, loser_id):
        await catalog.upsert_entity(
            entity_id=entity_id,
            canonical_name="Jazz",
            entity_type="topic",
        )
    await _seed_claim(store, claim_id=claim_id, object_entity_id=loser_id)
    await _seed_claim_target(
        store,
        claim_id=claim_id,
        object_entity_id=loser_id,
        target_kind=target_kind,
        authority_ref="correction:independent",
        extra_evidence_event_ids=("evt-independent",),
    )
    await L2EntityMaintenance(db_path=store.db_path)._merge_entity_into(
        winner_id,
        loser_id,
    )

    await store.forget_entity(entity_id=loser_id)

    target = await _target_row_for_entity(
        store,
        target_kind=target_kind,
        entity_id=winner_id,
    )
    assert target["status"] != "archived"
    assert target["authority_ref"] == "correction:independent"
    assert json.loads(str(target["evidence_json"])) == ["evt-independent"]
