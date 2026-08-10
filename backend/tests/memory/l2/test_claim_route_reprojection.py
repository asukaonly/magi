"""Backlog visibility and idempotent Claim route reprojection tests."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import aiosqlite
import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.claims.identity import projection_outcome_id
from magi.memory.l2.claims.reprojection import (
    list_unrouted_claim_backlog,
    reproject_stale_claim_routes,
)
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.entities.maintenance import L2EntityMaintenance
from magi.memory.l2.semantic_routing import (
    ROUTE_CONTRACT_VERSION,
    SemanticRouteDecision,
    SemanticRouteInput,
    derive_semantic_route,
)
from magi.user_profile.portrait_claim_query import list_tentative_portrait_claims
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder


async def _seed_claim(
    store,  # type: ignore[no-untyped-def]
    *,
    claim_id: str,
    predicate: str,
    created_at: float,
    object_entity_id: str | None = None,
    user_id: str | None = None,
    subject_ref: str = "person:user",
    subject_type: str = "person",
    fact_kind: str = "explicit_fact",
    object_type: str = "topic",
    object_value: object = "Jazz",
    evidence_event_id: str | None = None,
    evidence_event_time: float | None = None,
    temporal_cue: str = "current",
) -> None:
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
            ) VALUES (
                :claim_id, :identity_key, 1, 1, 'attempt:seed', 'test', :user_id,
                :subject_ref, :subject_type, :predicate, :fact_kind,
                :object_type, 'positive', 'concrete', 0.9,
                :object_value_json, :object_surface, :temporal_cue, 'active',
                :created_at, :created_at
            )
            """,
            {
                "claim_id": claim_id,
                "identity_key": f"identity:{claim_id}",
                "user_id": user_id,
                "subject_ref": subject_ref,
                "subject_type": subject_type,
                "predicate": predicate,
                "fact_kind": fact_kind,
                "object_type": object_type,
                "object_value_json": json.dumps(object_value, ensure_ascii=False),
                "object_surface": str(object_value),
                "temporal_cue": temporal_cue,
                "created_at": created_at,
            },
        )
        if evidence_event_id is not None:
            await db.execute(
                """
                INSERT INTO l2_claim_evidence(
                    claim_id, event_id, link_role, required_for_grounding,
                    event_time, timestamp_confidence, timestamp_quality,
                    evidence_rule_version, evidence_mode, source_type,
                    source_domain, author_type, evidence_class, created_at
                ) VALUES (
                    ?, ?, 'supporting', 1, ?, 'exact', 'source',
                    1, 'direct', 'chat', 'conversation', 'user',
                    'user_self_report', ?
                )
                """,
                (
                    claim_id,
                    evidence_event_id,
                    evidence_event_time if evidence_event_time is not None else created_at,
                    created_at,
                ),
            )
        if object_entity_id is not None:
            await db.execute(
                """
                INSERT INTO l2_claim_entity_refs(
                    claim_id, ref_role, entity_id, resolution_version, created_at
                ) VALUES (?, 'object', ?, 1, ?)
                """,
                (claim_id, object_entity_id, created_at),
            )
        await db.commit()


async def _seed_route_outcome(
    store,  # type: ignore[no-untyped-def]
    *,
    claim_id: str,
    attempt_key: str,
    outcome: str,
    route_contract_version: int,
    created_at: float,
    target_id: str | None = None,
    target_slot_key: str | None = None,
    details: dict[str, object] | None = None,
    reason_code: str = "seed",
) -> None:
    stored_target_id = target_id or f"seed:{claim_id}:{attempt_key}"
    outcome_id = projection_outcome_id(
        claim_id=claim_id,
        attempt_key=attempt_key,
        target_kind="route",
        target_id=stored_target_id,
    )
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO l2_claim_projection_outcomes(
                outcome_id, claim_id, attempt_key, target_kind, target_id,
                target_slot_key, route_contract_version, outcome, reason_code,
                details_json, created_at
            ) VALUES (?, ?, ?, 'route', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outcome_id,
                claim_id,
                attempt_key,
                stored_target_id,
                target_slot_key,
                route_contract_version,
                outcome,
                reason_code,
                (
                    json.dumps(
                        details,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if details is not None
                    else None
                ),
                created_at,
            ),
        )
        await db.commit()


async def _seed_target_outcome(
    store,  # type: ignore[no-untyped-def]
    *,
    claim_id: str,
    attempt_key: str,
    target_kind: str,
    target_id: str,
    target_slot_key: str | None,
    route_contract_version: int,
    created_at: float,
) -> str:
    outcome_id = projection_outcome_id(
        claim_id=claim_id,
        attempt_key=attempt_key,
        target_kind=target_kind,
        target_id=target_id,
    )
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO l2_claim_projection_outcomes(
                outcome_id, claim_id, attempt_key, target_kind, target_id,
                target_slot_key, route_contract_version, outcome, reason_code,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'projected', 'seed', ?)
            """,
            (
                outcome_id,
                claim_id,
                attempt_key,
                target_kind,
                target_id,
                target_slot_key,
                route_contract_version,
                created_at,
            ),
        )
        await db.commit()
    return outcome_id


def _route_details(
    decision: SemanticRouteDecision,
    *,
    subject_resolution_version: int | None = None,
    object_resolution_version: int | None = None,
) -> dict[str, object]:
    details: dict[str, object] = {
        "semantic_route_id": decision.semantic_route_id,
        "family": decision.family,
        "trait_code": decision.trait_code,
        "object_role": decision.object_role.value,
        "value_fingerprint": decision.value_fingerprint,
        "semantic_target_key": decision.semantic_target_key,
        "object_surface": decision.object_surface,
        "normalized_target_text": decision.normalized_target_text,
        "target_entity_type": decision.target_entity_type,
        "goal_lineage_key": decision.goal_lineage_key,
        "target_window_key": decision.target_window_key,
        "scope_key": decision.scope_key,
    }
    if subject_resolution_version is not None:
        details["subject_resolution_version"] = subject_resolution_version
    if object_resolution_version is not None:
        details["object_resolution_version"] = object_resolution_version
    return details


def _derive_route(
    *,
    claim_id: str,
    predicate: str,
    fact_kind: str,
    object_type: str,
    object_value: object,
    object_entity_id: str | None = None,
    temporal_cue: str = "current",
) -> SemanticRouteDecision:
    return derive_semantic_route(
        SemanticRouteInput(
            claim_id=claim_id,
            subject_id="user:u1",
            subject_type="user",
            canonical_predicate=predicate,
            fact_kind=fact_kind,
            object_type=object_type,
            object_value=object_value,
            object_entity_id=object_entity_id,
            temporal_cue=temporal_cue,
            specificity="concrete",
            target_from=None,
            target_to=None,
            raw_time_expression="",
            time_resolution="unscheduled",
        )
    )


async def _seed_assertion_target(
    store,  # type: ignore[no-untyped-def]
    *,
    slot_key: str,
    family: str,
    trait_name: str,
    trait_value: object,
    evidence_event_ids: list[str],
    authority_ref: str | None = None,
    target_entity_id: str = "",
    target_entity_type: str = "",
) -> str:
    assertion_id = await store.upsert_assertion_candidate(
        {
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": family,
            "trait_name": trait_name,
            "trait_value": trait_value,
            "confidence_score": 0.9,
            "evidence_events": evidence_event_ids,
            "volatility_index": 0.05,
            "source_domain": "conversation",
            "inference_depth": "explicit",
            "validation_state": "stable",
            "first_inferred_at": 10.0,
            "last_validated_at": 20.0,
            "target_entity_id": target_entity_id,
            "target_entity_type": target_entity_type,
            "temporal_scope": "persistent",
            "semantic_route_slot_key": slot_key,
        }
    )
    if authority_ref is not None:
        async with sqlite_connection_async(store.db_path) as db:
            await db.execute(
                "UPDATE tom_trait_assertions SET authority_ref = ? WHERE assertion_id = ?",
                (authority_ref, assertion_id),
            )
            await db.commit()
    return assertion_id


async def _seed_relationship_target(
    store,  # type: ignore[no-untyped-def]
    *,
    predicate: str,
    object_id: str,
    object_type: str,
    evidence_event_ids: list[str],
    authority_ref: str | None = None,
) -> tuple[str, str]:
    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate=predicate,
        object_id=object_id,
        object_type=object_type,
        fact_kind="explicit_fact",
        evidence_event_ids=evidence_event_ids,
        confidence=0.9,
        observed_at=20.0,
        source_type="conversation",
        extraction_method="llm_phase1_grounded",
    )
    async with sqlite_connection_async(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        if authority_ref is not None:
            await db.execute(
                "UPDATE knowledge_graph SET authority_ref = ? WHERE triple_id = ?",
                (authority_ref, triple_id),
            )
        async with db.execute(
            "SELECT slot_key FROM knowledge_graph WHERE triple_id = ?",
            (triple_id,),
        ) as cursor:
            row = await cursor.fetchone()
        await db.commit()
    assert row is not None
    return triple_id, str(row["slot_key"])


async def _seed_object_ref(
    store,  # type: ignore[no-untyped-def]
    *,
    claim_id: str,
    entity_id: str,
    resolution_version: int,
    created_at: float,
) -> None:
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO l2_claim_entity_refs(
                claim_id, ref_role, entity_id, resolution_version, created_at
            ) VALUES (?, 'object', ?, ?, ?)
            """,
            (claim_id, entity_id, resolution_version, created_at),
        )
        await db.commit()


async def _mark_claim_forgotten(
    store,  # type: ignore[no-untyped-def]
    *,
    claim_id: str,
) -> None:
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """
            UPDATE l2_grounded_claims
            SET availability = 'forgotten',
                origin_attempt_key = NULL,
                profile_id = NULL,
                user_id = NULL,
                subject_ref = NULL,
                subject_type = NULL,
                canonical_predicate = NULL,
                fact_kind = NULL,
                object_type = NULL,
                polarity = NULL,
                specificity = NULL,
                confidence = NULL,
                object_value_json = NULL,
                object_surface = NULL,
                temporal_cue = NULL,
                fact_valid_from = NULL,
                fact_valid_to = NULL,
                target_from = NULL,
                target_to = NULL,
                raw_time_frame_json = NULL,
                forgotten_at = 100.0,
                updated_at = 100.0
            WHERE claim_id = ?
            """,
            (claim_id,),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_unrouted_backlog_groups_only_latest_active_route_outcomes(
    l2_store_with_schema,
) -> None:
    for claim_id, predicate, created_at in (
        ("claim-a1", "ALLERGIC_TO", 10.0),
        ("claim-a2", "ALLERGIC_TO", 20.0),
        ("claim-routed", "LIKES", 30.0),
        ("claim-custom", "CUSTOM_SIGNAL", 40.0),
        ("claim-forgotten", "CUSTOM_SIGNAL", 50.0),
    ):
        await _seed_claim(
            l2_store_with_schema,
            claim_id=claim_id,
            predicate=predicate,
            created_at=created_at,
        )

    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id="claim-a1",
        attempt_key="attempt:a1",
        outcome="unrouted",
        route_contract_version=1,
        created_at=11.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id="claim-a2",
        attempt_key="attempt:a2",
        outcome="unrouted",
        route_contract_version=1,
        created_at=21.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id="claim-routed",
        attempt_key="attempt:routed-old",
        outcome="unrouted",
        route_contract_version=0,
        created_at=31.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id="claim-routed",
        attempt_key="attempt:routed-new",
        outcome="routed",
        route_contract_version=1,
        created_at=32.0,
    )
    for claim_id, created_at in (("claim-custom", 41.0), ("claim-forgotten", 51.0)):
        await _seed_route_outcome(
            l2_store_with_schema,
            claim_id=claim_id,
            attempt_key=f"attempt:{claim_id}",
            outcome="unrouted",
            route_contract_version=1,
            created_at=created_at,
        )
    await _mark_claim_forgotten(
        l2_store_with_schema,
        claim_id="claim-forgotten",
    )

    groups = await list_unrouted_claim_backlog(l2_store_with_schema.db_path)

    assert [group.canonical_predicate for group in groups] == [
        "ALLERGIC_TO",
        "CUSTOM_SIGNAL",
    ]
    assert groups[0].claim_count == 2
    assert groups[0].oldest_claim_at == 10.0
    assert groups[0].newest_claim_at == 20.0
    assert groups[1].claim_count == 1


@pytest.mark.asyncio
async def test_reproject_stale_routes_appends_history_once_per_contract(
    l2_store_with_schema,
) -> None:
    await _seed_claim(
        l2_store_with_schema,
        claim_id="claim-old-route",
        predicate="LIKES",
        created_at=10.0,
        object_entity_id="topic:jazz",
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id="claim-old-route",
        attempt_key="attempt:old-route",
        outcome="unrouted",
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        created_at=11.0,
    )
    await _seed_claim(
        l2_store_with_schema,
        claim_id="claim-unrouted",
        predicate="ALLERGIC_TO",
        created_at=20.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id="claim-unrouted",
        attempt_key="attempt:unrouted",
        outcome="unrouted",
        route_contract_version=ROUTE_CONTRACT_VERSION,
        created_at=21.0,
    )
    await _seed_claim(
        l2_store_with_schema,
        claim_id="claim-current",
        predicate="LIKES",
        created_at=30.0,
        object_entity_id="topic:jazz",
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id="claim-current",
        attempt_key="attempt:current",
        outcome="routed",
        route_contract_version=ROUTE_CONTRACT_VERSION,
        created_at=31.0,
    )
    await _seed_claim(
        l2_store_with_schema,
        claim_id="claim-future-version",
        predicate="ALLERGIC_TO",
        created_at=40.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id="claim-future-version",
        attempt_key="attempt:future",
        outcome="unrouted",
        route_contract_version=ROUTE_CONTRACT_VERSION + 1,
        created_at=41.0,
    )

    first = await reproject_stale_claim_routes(l2_store_with_schema)
    second = await reproject_stale_claim_routes(l2_store_with_schema)

    assert first.candidates_selected == 2
    assert first.outcomes_appended == 2
    assert first.routed == 1
    assert first.unrouted == 1
    assert first.failed == 0
    assert second.candidates_selected == 0
    assert second.outcomes_appended == 0
    assert second.outcomes_already_present == 0

    old_route_history = await l2_store_with_schema.list_claim_projection_outcomes(
        claim_id="claim-old-route"
    )
    assert len(old_route_history) == 2
    assert [row["route_contract_version"] for row in old_route_history] == [
        ROUTE_CONTRACT_VERSION - 1,
        ROUTE_CONTRACT_VERSION,
    ]
    assert [row["outcome"] for row in old_route_history] == ["unrouted", "routed"]
    assert old_route_history[-1]["outcome"] == "routed"
    assert old_route_history[-1]["attempt_key"] == (
        f"route-reproject:v{ROUTE_CONTRACT_VERSION}:r1:claim-old-route"
    )
    assert old_route_history[-1]["target_slot_key"]

    unrouted_history = await l2_store_with_schema.list_claim_projection_outcomes(
        claim_id="claim-unrouted"
    )
    assert len(unrouted_history) == 2
    assert [row["outcome"] for row in unrouted_history] == ["unrouted", "unrouted"]
    assert (
        len(await l2_store_with_schema.list_claim_projection_outcomes(claim_id="claim-current"))
        == 1
    )
    assert (
        len(
            await l2_store_with_schema.list_claim_projection_outcomes(
                claim_id="claim-future-version"
            )
        )
        == 1
    )


@pytest.mark.asyncio
async def test_route_upgrade_retires_one_off_preference_relationship_only(
    l2_store_with_schema,
) -> None:
    claim_id = "claim-one-off-preference"
    attempt_key = "attempt:one-off-preference"
    event_id = "event-one-off-preference"
    object_entity_id = "topic:jazz"
    await _seed_claim(
        l2_store_with_schema,
        claim_id=claim_id,
        predicate="LIKES",
        fact_kind="explicit_fact",
        object_type="topic",
        object_value="Jazz",
        object_entity_id=object_entity_id,
        user_id="u1",
        subject_ref="user:u1",
        subject_type="user",
        evidence_event_id=event_id,
        temporal_cue="one_off",
        created_at=10.0,
    )
    route = _derive_route(
        claim_id=claim_id,
        predicate="LIKES",
        fact_kind="explicit_fact",
        object_type="topic",
        object_value="Jazz",
        object_entity_id=object_entity_id,
        temporal_cue="one_off",
    )
    assert route.slot_key is not None
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=attempt_key,
        outcome="routed",
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        target_id=route.route_key,
        target_slot_key=route.slot_key,
        details=_route_details(route),
        reason_code=route.reason_code,
        created_at=11.0,
    )
    assertion_id = await _seed_assertion_target(
        l2_store_with_schema,
        slot_key=route.slot_key,
        family="preference_profile",
        trait_name="preference.affinity",
        trait_value="like",
        evidence_event_ids=[event_id],
        target_entity_id=object_entity_id,
        target_entity_type="topic",
    )
    triple_id, relationship_slot_key = await _seed_relationship_target(
        l2_store_with_schema,
        predicate="LIKES",
        object_id=object_entity_id,
        object_type="topic",
        evidence_event_ids=[event_id],
    )
    for target_kind, target_id, target_slot_key in (
        ("assertion", assertion_id, route.slot_key),
        ("relationship", triple_id, relationship_slot_key),
    ):
        await _seed_target_outcome(
            l2_store_with_schema,
            claim_id=claim_id,
            attempt_key=attempt_key,
            target_kind=target_kind,
            target_id=target_id,
            target_slot_key=target_slot_key,
            route_contract_version=ROUTE_CONTRACT_VERSION - 1,
            created_at=12.0,
        )

    result = await reproject_stale_claim_routes(l2_store_with_schema)

    assert result.candidates_selected == 1
    assert result.target_outcomes_invalidated == 2
    assert result.target_outcomes_revalidated == 1
    assert result.targets_archived == 1
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT status FROM tom_trait_assertions WHERE assertion_id = ?",
            (assertion_id,),
        ) as cursor:
            assertion = await cursor.fetchone()
        async with db.execute(
            "SELECT status, status_reason FROM knowledge_graph WHERE triple_id = ?",
            (triple_id,),
        ) as cursor:
            relationship = await cursor.fetchone()
    assert assertion is not None and assertion["status"] != "archived"
    assert relationship is not None
    assert relationship["status"] == "archived"
    assert relationship["status_reason"] == "route_contract_changed"


@pytest.mark.asyncio
async def test_reprojection_retries_after_object_resolution_changes(
    l2_store_with_schema,
) -> None:
    await _seed_claim(
        l2_store_with_schema,
        claim_id="claim-resolves-later",
        predicate="LIKES",
        created_at=10.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id="claim-resolves-later",
        attempt_key="attempt:unresolved",
        outcome="unrouted",
        route_contract_version=ROUTE_CONTRACT_VERSION,
        created_at=11.0,
    )

    unresolved = await reproject_stale_claim_routes(l2_store_with_schema)
    unchanged = await reproject_stale_claim_routes(l2_store_with_schema)
    await _seed_object_ref(
        l2_store_with_schema,
        claim_id="claim-resolves-later",
        entity_id="topic:jazz",
        resolution_version=1,
        created_at=12.0,
    )
    resolved = await reproject_stale_claim_routes(l2_store_with_schema)
    stable = await reproject_stale_claim_routes(l2_store_with_schema)

    assert unresolved.candidates_selected == 1
    assert unresolved.outcomes_appended == 1
    assert unresolved.routed == 1
    assert unchanged.candidates_selected == 0
    assert resolved.candidates_selected == 1
    assert resolved.outcomes_appended == 1
    assert resolved.routed == 1
    assert stable.candidates_selected == 0

    history = await l2_store_with_schema.list_claim_projection_outcomes(
        claim_id="claim-resolves-later"
    )
    assert len(history) == 3
    assert [row["outcome"] for row in history] == ["unrouted", "routed", "routed"]
    assert [row["attempt_key"] for row in history[1:]] == [
        f"route-reproject:v{ROUTE_CONTRACT_VERSION}:r0:claim-resolves-later",
        f"route-reproject:v{ROUTE_CONTRACT_VERSION}:r1:claim-resolves-later",
    ]


@pytest.mark.asyncio
async def test_reprojection_converges_when_stale_route_has_future_created_at(
    l2_store_with_schema,
) -> None:
    claim_id = "claim-clock-rollback"
    await _seed_claim(
        l2_store_with_schema,
        claim_id=claim_id,
        predicate="LIKES",
        object_entity_id="topic:jazz",
        created_at=10.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key="attempt:v2:future-clock",
        outcome="unrouted",
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        created_at=4_000_000_000.0,
    )

    first = await reproject_stale_claim_routes(l2_store_with_schema)
    second = await reproject_stale_claim_routes(l2_store_with_schema)
    third = await reproject_stale_claim_routes(l2_store_with_schema)

    assert [pass_stats.candidates_selected for pass_stats in (first, second, third)] == [1, 0, 0]
    assert [pass_stats.outcomes_appended for pass_stats in (first, second, third)] == [
        1,
        0,
        0,
    ]
    history = await l2_store_with_schema.list_claim_projection_outcomes(claim_id=claim_id)
    current_route = max(
        (row for row in history if row["target_kind"] == "route"),
        key=lambda row: (row["route_contract_version"], row["created_at"]),
    )
    assert current_route["route_contract_version"] == ROUTE_CONTRACT_VERSION
    assert current_route["outcome"] == "routed"
    assert await list_unrouted_claim_backlog(l2_store_with_schema.db_path) == []


@pytest.mark.asyncio
async def test_reprojection_prefers_current_resolution_during_clock_rollback(
    l2_store_with_schema,
) -> None:
    claim_id = "claim-resolution-clock-rollback"
    unresolved_route = _derive_route(
        claim_id=claim_id,
        predicate="LIKES",
        fact_kind="explicit_fact",
        object_type="topic",
        object_value="Jazz",
    )
    assert unresolved_route.disposition.value == "routed"
    assert unresolved_route.target_entity_id is None
    await _seed_claim(
        l2_store_with_schema,
        claim_id=claim_id,
        predicate="LIKES",
        created_at=10.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=f"route-reproject:v{ROUTE_CONTRACT_VERSION}:r0:{claim_id}",
        outcome=unresolved_route.disposition.value,
        route_contract_version=ROUTE_CONTRACT_VERSION,
        target_id="predicate:LIKES",
        details=_route_details(unresolved_route, object_resolution_version=0),
        reason_code=unresolved_route.reason_code,
        created_at=4_000_000_000.0,
    )
    await _seed_object_ref(
        l2_store_with_schema,
        claim_id=claim_id,
        entity_id="topic:jazz",
        resolution_version=1,
        created_at=11.0,
    )

    first = await reproject_stale_claim_routes(l2_store_with_schema)
    second = await reproject_stale_claim_routes(l2_store_with_schema)

    assert first.candidates_selected == 1
    assert first.routed == 1
    assert first.outcomes_appended == 1
    assert second.candidates_selected == 0
    assert await list_unrouted_claim_backlog(l2_store_with_schema.db_path) == []


@pytest.mark.asyncio
async def test_entity_merge_revalidates_rekeyed_assertion_receipt(
    l2_store_with_schema,
) -> None:
    claim_id = "claim-entity-merge-receipt"
    old_attempt_key = "attempt:before-entity-merge"
    loser_id = "topic:merge-loser"
    winner_id = "topic:merge-winner"
    event_id = "event:entity-merge-receipt"
    catalog = L2EntityCatalog(
        db_path=l2_store_with_schema.db_path,
        vector_enabled=False,
    )
    for entity_id in (loser_id, winner_id):
        await catalog.upsert_entity(
            entity_id=entity_id,
            canonical_name="Jazz",
            entity_type="topic",
        )
    await _seed_claim(
        l2_store_with_schema,
        claim_id=claim_id,
        predicate="LIKES",
        fact_kind="stable_preference",
        object_type="topic",
        object_value="Jazz",
        object_entity_id=loser_id,
        user_id="u1",
        subject_ref="user:u1",
        subject_type="user",
        evidence_event_id=event_id,
        created_at=10.0,
    )
    old_route = _derive_route(
        claim_id=claim_id,
        predicate="LIKES",
        fact_kind="stable_preference",
        object_type="topic",
        object_value="Jazz",
        object_entity_id=loser_id,
    )
    assert old_route.slot_key is not None
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=old_attempt_key,
        outcome="routed",
        route_contract_version=ROUTE_CONTRACT_VERSION,
        target_id=old_route.route_key,
        target_slot_key=old_route.slot_key,
        details=_route_details(old_route),
        reason_code=old_route.reason_code,
        created_at=11.0,
    )
    assertion_id = await _seed_assertion_target(
        l2_store_with_schema,
        slot_key=old_route.slot_key,
        family="preference_profile",
        trait_name="preference.affinity",
        trait_value="like",
        evidence_event_ids=[event_id],
        target_entity_id=loser_id,
        target_entity_type="topic",
    )
    old_receipt_id = await _seed_target_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=old_attempt_key,
        target_kind="assertion",
        target_id=assertion_id,
        target_slot_key=old_route.slot_key,
        route_contract_version=ROUTE_CONTRACT_VERSION,
        created_at=12.0,
    )

    await L2EntityMaintenance(db_path=l2_store_with_schema.db_path)._merge_entity_into(
        winner_id,
        loser_id,
    )
    current_route = _derive_route(
        claim_id=claim_id,
        predicate="LIKES",
        fact_kind="stable_preference",
        object_type="topic",
        object_value="Jazz",
        object_entity_id=winner_id,
    )
    assert current_route.slot_key is not None

    first = await reproject_stale_claim_routes(l2_store_with_schema)
    second = await reproject_stale_claim_routes(l2_store_with_schema)

    assert first.candidates_selected == 1
    assert first.outcomes_appended == 1
    assert first.target_outcomes_revalidated == 1
    assert first.target_outcomes_invalidated == 1
    assert first.targets_archived == 0
    assert second.candidates_selected == 0
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT assertion_id, target_entity_id, slot_key, status
            FROM tom_trait_assertions WHERE assertion_id = ?
            """,
            (assertion_id,),
        ) as cursor:
            assertion = await cursor.fetchone()
        async with db.execute(
            """
            SELECT outcome_id, attempt_key, target_slot_key, reason_code,
                   details_json, invalidated_at, invalidated_reason
            FROM l2_claim_projection_outcomes
            WHERE claim_id = ? AND target_kind = 'assertion'
            ORDER BY created_at, outcome_id
            """,
            (claim_id,),
        ) as cursor:
            receipts = await cursor.fetchall()
    assert assertion is not None
    assert assertion["target_entity_id"] == winner_id
    assert assertion["slot_key"] != old_route.slot_key
    assert assertion["status"] != "archived"
    assert len(receipts) == 2
    assert receipts[0]["outcome_id"] == old_receipt_id
    assert receipts[0]["invalidated_reason"] == "route_contract_revalidated"
    assert receipts[1]["invalidated_at"] is None
    assert receipts[1]["target_slot_key"] == assertion["slot_key"]
    assert receipts[1]["attempt_key"] == (
        f"route-reproject:v{ROUTE_CONTRACT_VERSION}:r2:{claim_id}"
    )
    assert json.loads(receipts[1]["details_json"])["supersedes_outcome_ids"] == [old_receipt_id]


@pytest.mark.asyncio
async def test_reprojection_coalesces_duplicate_stale_target_receipts(
    l2_store_with_schema,
) -> None:
    claim_id = "claim-duplicate-stale-receipts"
    event_id = "event:duplicate-stale-receipts"
    object_entity_id = "topic:jazz"
    route = _derive_route(
        claim_id=claim_id,
        predicate="LIKES",
        fact_kind="stable_preference",
        object_type="topic",
        object_value="Jazz",
        object_entity_id=object_entity_id,
    )
    assert route.slot_key is not None
    await _seed_claim(
        l2_store_with_schema,
        claim_id=claim_id,
        predicate="LIKES",
        fact_kind="stable_preference",
        object_type="topic",
        object_value="Jazz",
        object_entity_id=object_entity_id,
        user_id="u1",
        subject_ref="user:u1",
        subject_type="user",
        evidence_event_id=event_id,
        created_at=10.0,
    )
    assertion_id = await _seed_assertion_target(
        l2_store_with_schema,
        slot_key=route.slot_key,
        family="preference_profile",
        trait_name="preference.affinity",
        trait_value="like",
        evidence_event_ids=[event_id],
        target_entity_id=object_entity_id,
        target_entity_type="topic",
    )
    stale_receipt_ids: list[str] = []
    for index, attempt_key in enumerate(("attempt:stale-a", "attempt:stale-b")):
        await _seed_route_outcome(
            l2_store_with_schema,
            claim_id=claim_id,
            attempt_key=attempt_key,
            outcome="routed",
            route_contract_version=ROUTE_CONTRACT_VERSION - 1,
            target_id=route.route_key,
            target_slot_key=route.slot_key,
            details=_route_details(route),
            reason_code=route.reason_code,
            created_at=11.0 + index,
        )
        stale_receipt_ids.append(
            await _seed_target_outcome(
                l2_store_with_schema,
                claim_id=claim_id,
                attempt_key=attempt_key,
                target_kind="assertion",
                target_id=assertion_id,
                target_slot_key=route.slot_key,
                route_contract_version=ROUTE_CONTRACT_VERSION - 1,
                created_at=13.0 + index,
            )
        )

    first = await reproject_stale_claim_routes(l2_store_with_schema)
    second = await reproject_stale_claim_routes(l2_store_with_schema)

    assert first.failed == 0
    assert first.target_outcomes_revalidated == 1
    assert first.target_outcomes_invalidated == 2
    assert first.targets_archived == 0
    assert second.candidates_selected == 0
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT outcome_id, reason_code, details_json, invalidated_at,
                   invalidated_reason
            FROM l2_claim_projection_outcomes
            WHERE claim_id = ? AND target_kind = 'assertion'
            ORDER BY created_at, outcome_id
            """,
            (claim_id,),
        ) as cursor:
            receipts = await cursor.fetchall()
    active_receipts = [row for row in receipts if row["invalidated_at"] is None]
    assert len(active_receipts) == 1
    assert active_receipts[0]["reason_code"] == "route_contract_revalidated"
    assert json.loads(active_receipts[0]["details_json"])["supersedes_outcome_ids"] == sorted(
        stale_receipt_ids
    )
    assert {
        row["invalidated_reason"] for row in receipts if row["outcome_id"] in stale_receipt_ids
    } == {"route_contract_revalidated"}


@pytest.mark.asyncio
async def test_reprojection_keeps_existing_current_receipt_and_retires_stale_duplicate(
    l2_store_with_schema,
) -> None:
    claim_id = "claim-current-and-stale-receipts"
    event_id = "event:current-and-stale-receipts"
    object_entity_id = "topic:jazz"
    current_attempt_key = f"route-reproject:v{ROUTE_CONTRACT_VERSION}:r1:{claim_id}"
    route = _derive_route(
        claim_id=claim_id,
        predicate="LIKES",
        fact_kind="stable_preference",
        object_type="topic",
        object_value="Jazz",
        object_entity_id=object_entity_id,
    )
    assert route.slot_key is not None
    await _seed_claim(
        l2_store_with_schema,
        claim_id=claim_id,
        predicate="LIKES",
        fact_kind="stable_preference",
        object_type="topic",
        object_value="Jazz",
        object_entity_id=object_entity_id,
        user_id="u1",
        subject_ref="user:u1",
        subject_type="user",
        evidence_event_id=event_id,
        created_at=10.0,
    )
    assertion_id = await _seed_assertion_target(
        l2_store_with_schema,
        slot_key=route.slot_key,
        family="preference_profile",
        trait_name="preference.affinity",
        trait_value="like",
        evidence_event_ids=[event_id],
        target_entity_id=object_entity_id,
        target_entity_type="topic",
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key="attempt:stale",
        outcome="routed",
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        target_id=route.route_key,
        target_slot_key=route.slot_key,
        details=_route_details(route),
        reason_code=route.reason_code,
        created_at=11.0,
    )
    stale_receipt_id = await _seed_target_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key="attempt:stale",
        target_kind="assertion",
        target_id=assertion_id,
        target_slot_key=route.slot_key,
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        created_at=12.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=current_attempt_key,
        outcome="routed",
        route_contract_version=ROUTE_CONTRACT_VERSION,
        target_id=route.route_key,
        target_slot_key=route.slot_key,
        details=_route_details(
            route,
            subject_resolution_version=0,
            object_resolution_version=1,
        ),
        reason_code=route.reason_code,
        created_at=13.0,
    )
    current_receipt_id = await _seed_target_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=current_attempt_key,
        target_kind="assertion",
        target_id=assertion_id,
        target_slot_key=route.slot_key,
        route_contract_version=ROUTE_CONTRACT_VERSION,
        created_at=14.0,
    )

    first = await reproject_stale_claim_routes(l2_store_with_schema)
    second = await reproject_stale_claim_routes(l2_store_with_schema)

    assert first.candidates_selected == 1
    assert first.outcomes_appended == 0
    assert first.outcomes_already_present == 1
    assert first.target_outcomes_revalidated == 0
    assert first.target_outcomes_invalidated == 1
    assert first.targets_archived == 0
    assert second.candidates_selected == 0
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT outcome_id, reason_code, details_json, invalidated_at,
                   invalidated_reason
            FROM l2_claim_projection_outcomes
            WHERE outcome_id IN (?, ?)
            ORDER BY outcome_id
            """,
            (stale_receipt_id, current_receipt_id),
        ) as cursor:
            receipts = {row["outcome_id"]: row for row in await cursor.fetchall()}
    assert receipts[stale_receipt_id]["invalidated_reason"] == ("route_contract_revalidated")
    assert receipts[current_receipt_id]["invalidated_at"] is None
    assert receipts[current_receipt_id]["reason_code"] == "seed"
    assert receipts[current_receipt_id]["details_json"] is None


@pytest.mark.asyncio
async def test_concurrent_reprojection_keeps_one_outcome_per_attempt(
    l2_store_with_schema,
) -> None:
    await _seed_claim(
        l2_store_with_schema,
        claim_id="claim-concurrent",
        predicate="LIKES",
        created_at=10.0,
        object_entity_id="topic:jazz",
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id="claim-concurrent",
        attempt_key="attempt:old",
        outcome="unrouted",
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        created_at=11.0,
    )

    await asyncio.gather(
        reproject_stale_claim_routes(
            l2_store_with_schema,
        ),
        reproject_stale_claim_routes(
            l2_store_with_schema,
        ),
    )

    history = await l2_store_with_schema.list_claim_projection_outcomes(claim_id="claim-concurrent")
    assert len(history) == 2
    assert [row["route_contract_version"] for row in history] == [
        ROUTE_CONTRACT_VERSION - 1,
        ROUTE_CONTRACT_VERSION,
    ]
    assert history[-1]["attempt_key"] == (
        f"route-reproject:v{ROUTE_CONTRACT_VERSION}:r1:claim-concurrent"
    )


@pytest.mark.asyncio
async def test_maintenance_reports_structured_unrouted_backlog(
    l2_store_with_schema,
) -> None:
    await _seed_claim(
        l2_store_with_schema,
        claim_id="claim-maintenance",
        predicate="ALLERGIC_TO",
        created_at=10.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id="claim-maintenance",
        attempt_key="attempt:maintenance",
        outcome="unrouted",
        route_contract_version=ROUTE_CONTRACT_VERSION,
        created_at=11.0,
    )
    maintenance = L2EntityMaintenance(
        db_path=l2_store_with_schema.db_path,
        cognition_store=l2_store_with_schema,
    )

    with patch("magi.memory.l2.entities.maintenance.logger") as maintenance_logger:
        stats = await maintenance.run(
            resolve_ghosts=False,
            merge_fragments=False,
            prune_orphans=False,
            expire_future_intents=False,
            expire_decayed_assertions=False,
            clean_stale_snapshots=False,
            reconcile_stale=False,
            consolidate_open_predicates=False,
            archive_stale_edges=False,
            purge_terminal_edges=False,
            consolidate_episodes=False,
        )

    assert stats.unrouted_claim_count == 1
    assert stats.unrouted_claim_backlog == [
        {
            "canonical_predicate": "ALLERGIC_TO",
            "claim_count": 1,
            "oldest_claim_at": 10.0,
            "newest_claim_at": 10.0,
        }
    ]
    assert stats.claim_route_candidates_selected == 1
    assert stats.claim_route_outcomes_appended == 1
    assert stats.claim_route_reprojection_failed == 0
    maintenance_logger.info.assert_any_call(
        "L2 unrouted Claim backlog",
        total_claims=1,
        route_contract_version=ROUTE_CONTRACT_VERSION,
        groups=stats.unrouted_claim_backlog,
    )


@pytest.mark.asyncio
async def test_route_upgrade_archives_stale_targets_at_product_read_boundaries(
    l2_store_with_schema,
) -> None:
    claim_id = "claim-invalid-birth-date"
    attempt_key = "attempt:v2:invalid-birth-date"
    event_id = "event-invalid-birth-date"
    prior_route = _derive_route(
        claim_id=claim_id,
        predicate="BIRTH_DATE",
        fact_kind="explicit_fact",
        object_type="concept",
        object_value="1990-02-03",
    )
    assert prior_route.can_project_assertion
    assert prior_route.slot_key is not None
    await _seed_claim(
        l2_store_with_schema,
        claim_id=claim_id,
        predicate="BIRTH_DATE",
        fact_kind="stable_preference",
        object_type="concept",
        object_value="1990-02-03",
        user_id="u1",
        subject_ref="user:u1",
        subject_type="user",
        evidence_event_id=event_id,
        created_at=10.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=attempt_key,
        outcome="routed",
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        target_id=prior_route.route_key,
        target_slot_key=prior_route.slot_key,
        details=_route_details(prior_route),
        created_at=11.0,
    )
    assertion_id = await _seed_assertion_target(
        l2_store_with_schema,
        slot_key=prior_route.slot_key,
        family="identity_profile",
        trait_name="identity.birth_date",
        trait_value="1990-02-03",
        evidence_event_ids=[event_id],
    )
    triple_id, relationship_slot_key = await _seed_relationship_target(
        l2_store_with_schema,
        predicate="BIRTH_DATE",
        object_id="concept:1990-02-03",
        object_type="concept",
        evidence_event_ids=[event_id],
    )
    assertion_outcome_id = await _seed_target_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=attempt_key,
        target_kind="assertion",
        target_id=assertion_id,
        target_slot_key=prior_route.slot_key,
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        created_at=12.0,
    )
    relationship_outcome_id = await _seed_target_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=attempt_key,
        target_kind="relationship",
        target_id=triple_id,
        target_slot_key=relationship_slot_key,
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        created_at=12.0,
    )

    assert {
        row["assertion_id"]
        for row in await l2_store_with_schema.list_current_assertions(entity_id="user:u1")
    } == {assertion_id}
    assert {
        row["triple_id"]
        for row in await l2_store_with_schema.list_current_relationships(subject_id="user:u1")
    } == {triple_id}
    portrait_before = await UserPortraitProjectionBuilder(l2_store_with_schema).build("u1")
    assert f"assertion:{assertion_id}" in portrait_before.evidence_refs

    first = await reproject_stale_claim_routes(l2_store_with_schema)
    second = await reproject_stale_claim_routes(l2_store_with_schema)

    assert first.candidates_selected == 1
    assert first.outcomes_appended == 1
    assert first.unrouted == 1
    assert first.target_outcomes_invalidated == 2
    assert first.targets_archived == 2
    assert first.failed == 0
    assert second.candidates_selected == 0
    history = await l2_store_with_schema.list_claim_projection_outcomes(claim_id=claim_id)
    route_history = [row for row in history if row["target_kind"] == "route"]
    assert [row["route_contract_version"] for row in route_history] == [
        ROUTE_CONTRACT_VERSION - 1,
        ROUTE_CONTRACT_VERSION,
    ]
    assert route_history[-1]["outcome"] == "unrouted"
    assert route_history[-1]["reason_code"] == "predicate_fact_kind_mismatch"
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT outcome_id, invalidated_at, invalidated_reason
            FROM l2_claim_projection_outcomes
            WHERE outcome_id IN (?, ?)
            ORDER BY outcome_id
            """,
            (assertion_outcome_id, relationship_outcome_id),
        ) as cursor:
            retired_receipts = await cursor.fetchall()
        async with db.execute(
            "SELECT status FROM tom_trait_assertions WHERE assertion_id = ?",
            (assertion_id,),
        ) as cursor:
            assertion_row = await cursor.fetchone()
        async with db.execute(
            "SELECT status, status_reason FROM knowledge_graph WHERE triple_id = ?",
            (triple_id,),
        ) as cursor:
            relationship_row = await cursor.fetchone()
    assert len(retired_receipts) == 2
    assert all(row["invalidated_at"] is not None for row in retired_receipts)
    assert {row["invalidated_reason"] for row in retired_receipts} == {"route_contract_changed"}
    assert assertion_row is not None and assertion_row["status"] == "archived"
    assert relationship_row is not None
    assert relationship_row["status"] == "archived"
    assert relationship_row["status_reason"] == "route_contract_changed"
    assert await l2_store_with_schema.list_current_assertions(entity_id="user:u1") == []
    assert await l2_store_with_schema.list_current_relationships(subject_id="user:u1") == []
    assert (
        await list_tentative_portrait_claims(
            l2_store_with_schema,
            user_id="u1",
        )
        == []
    )
    portrait_after = await UserPortraitProjectionBuilder(l2_store_with_schema).build("u1")
    assert f"assertion:{assertion_id}" not in portrait_after.evidence_refs


@pytest.mark.asyncio
async def test_route_upgrade_preserves_shared_targets_and_recomputes_evidence(
    l2_store_with_schema,
) -> None:
    invalid_claim_id = "claim-invalid-like"
    valid_claim_id = "claim-valid-like"
    invalid_attempt = "attempt:v2:invalid-like"
    valid_attempt = "attempt:v3:valid-like"
    valid_route = _derive_route(
        claim_id=valid_claim_id,
        predicate="LIKES",
        fact_kind="stable_preference",
        object_type="topic",
        object_value="Jazz",
        object_entity_id="topic:jazz",
    )
    assert valid_route.can_project_assertion
    assert valid_route.slot_key is not None
    for claim_id, fact_kind, event_id, created_at in (
        (invalid_claim_id, "interaction_evidence", "event-invalid-like", 10.0),
        (valid_claim_id, "stable_preference", "event-valid-like", 20.0),
    ):
        await _seed_claim(
            l2_store_with_schema,
            claim_id=claim_id,
            predicate="LIKES",
            fact_kind=fact_kind,
            object_type="topic",
            object_value="Jazz",
            object_entity_id="topic:jazz",
            user_id="u1",
            subject_ref="user:u1",
            subject_type="user",
            evidence_event_id=event_id,
            evidence_event_time=created_at,
            created_at=created_at,
        )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=invalid_claim_id,
        attempt_key=invalid_attempt,
        outcome="routed",
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        target_id=valid_route.route_key,
        target_slot_key=valid_route.slot_key,
        details=_route_details(valid_route),
        created_at=11.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=valid_claim_id,
        attempt_key=valid_attempt,
        outcome="routed",
        route_contract_version=ROUTE_CONTRACT_VERSION,
        target_id=valid_route.route_key,
        target_slot_key=valid_route.slot_key,
        details=_route_details(valid_route),
        created_at=21.0,
    )
    assertion_id = await _seed_assertion_target(
        l2_store_with_schema,
        slot_key=valid_route.slot_key,
        family="preference_profile",
        trait_name="preference.affinity",
        trait_value="like",
        evidence_event_ids=["event-invalid-like", "event-valid-like"],
    )
    triple_id, relationship_slot_key = await _seed_relationship_target(
        l2_store_with_schema,
        predicate="LIKES",
        object_id="topic:jazz",
        object_type="topic",
        evidence_event_ids=["event-invalid-like", "event-valid-like"],
    )
    for claim_id, attempt_key, version, created_at in (
        (
            invalid_claim_id,
            invalid_attempt,
            ROUTE_CONTRACT_VERSION - 1,
            12.0,
        ),
        (valid_claim_id, valid_attempt, ROUTE_CONTRACT_VERSION, 22.0),
    ):
        await _seed_target_outcome(
            l2_store_with_schema,
            claim_id=claim_id,
            attempt_key=attempt_key,
            target_kind="assertion",
            target_id=assertion_id,
            target_slot_key=valid_route.slot_key,
            route_contract_version=version,
            created_at=created_at,
        )
        await _seed_target_outcome(
            l2_store_with_schema,
            claim_id=claim_id,
            attempt_key=attempt_key,
            target_kind="relationship",
            target_id=triple_id,
            target_slot_key=relationship_slot_key,
            route_contract_version=version,
            created_at=created_at,
        )

    result = await reproject_stale_claim_routes(l2_store_with_schema)

    assert result.candidates_selected == 1
    assert result.target_outcomes_invalidated == 2
    assert result.targets_archived == 0
    assert result.shared_targets_preserved == 2
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT evidence_events, status
            FROM tom_trait_assertions
            WHERE assertion_id = ?
            """,
            (assertion_id,),
        ) as cursor:
            assertion_row = await cursor.fetchone()
        async with db.execute(
            """
            SELECT evidence_event_ids, status
            FROM knowledge_graph
            WHERE triple_id = ?
            """,
            (triple_id,),
        ) as cursor:
            relationship_row = await cursor.fetchone()
        async with db.execute(
            """
            SELECT claim_id, invalidated_at
            FROM l2_claim_projection_outcomes
            WHERE target_id IN (?, ?)
              AND target_kind IN ('assertion', 'relationship')
            ORDER BY claim_id, target_kind
            """,
            (assertion_id, triple_id),
        ) as cursor:
            receipt_rows = await cursor.fetchall()
    assert assertion_row is not None and assertion_row["status"] != "archived"
    assert json.loads(assertion_row["evidence_events"]) == ["event-valid-like"]
    assert relationship_row is not None and relationship_row["status"] == "active"
    assert json.loads(relationship_row["evidence_event_ids"]) == ["event-valid-like"]
    assert all(
        (row["invalidated_at"] is not None) == (row["claim_id"] == invalid_claim_id)
        for row in receipt_rows
    )
    assert {
        row["assertion_id"]
        for row in await l2_store_with_schema.list_current_assertions(entity_id="user:u1")
    } == {assertion_id}
    assert {
        row["triple_id"]
        for row in await l2_store_with_schema.list_current_relationships(subject_id="user:u1")
    } == {triple_id}


@pytest.mark.asyncio
async def test_reprojection_repairs_targets_after_route_was_already_upgraded(
    l2_store_with_schema,
) -> None:
    claim_id = "claim-preupgraded-invalid"
    old_attempt = "attempt:v2:preupgraded-invalid"
    current_attempt = f"route-reproject:v{ROUTE_CONTRACT_VERSION}:r0:{claim_id}"
    event_id = "event-preupgraded-invalid"
    old_route = _derive_route(
        claim_id=claim_id,
        predicate="BIRTH_DATE",
        fact_kind="explicit_fact",
        object_type="concept",
        object_value="1990-02-03",
    )
    current_route = _derive_route(
        claim_id=claim_id,
        predicate="BIRTH_DATE",
        fact_kind="stable_preference",
        object_type="concept",
        object_value="1990-02-03",
    )
    assert old_route.slot_key is not None
    assert current_route.disposition.value == "unrouted"
    await _seed_claim(
        l2_store_with_schema,
        claim_id=claim_id,
        predicate="BIRTH_DATE",
        fact_kind="stable_preference",
        object_type="concept",
        object_value="1990-02-03",
        user_id="u1",
        subject_ref="user:u1",
        subject_type="user",
        evidence_event_id=event_id,
        created_at=10.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=old_attempt,
        outcome="routed",
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        target_id=old_route.route_key,
        target_slot_key=old_route.slot_key,
        details=_route_details(old_route),
        created_at=11.0,
    )
    assertion_id = await _seed_assertion_target(
        l2_store_with_schema,
        slot_key=old_route.slot_key,
        family="identity_profile",
        trait_name="identity.birth_date",
        trait_value="1990-02-03",
        evidence_event_ids=[event_id],
    )
    await _seed_target_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=old_attempt,
        target_kind="assertion",
        target_id=assertion_id,
        target_slot_key=old_route.slot_key,
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        created_at=12.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=current_attempt,
        outcome=current_route.disposition.value,
        route_contract_version=ROUTE_CONTRACT_VERSION,
        target_id="predicate:BIRTH_DATE",
        target_slot_key=None,
        details=_route_details(
            current_route,
            subject_resolution_version=0,
            object_resolution_version=0,
        ),
        reason_code=current_route.reason_code,
        created_at=13.0,
    )

    repaired = await reproject_stale_claim_routes(l2_store_with_schema)
    stable = await reproject_stale_claim_routes(l2_store_with_schema)

    assert repaired.candidates_selected == 1
    assert repaired.outcomes_appended == 0
    assert repaired.outcomes_already_present == 1
    assert repaired.target_outcomes_invalidated == 1
    assert repaired.targets_archived == 1
    assert stable.candidates_selected == 0
    assert await l2_store_with_schema.list_current_assertions(entity_id="user:u1") == []


@pytest.mark.asyncio
async def test_reprojection_revalidates_relationship_only_target_provenance(
    l2_store_with_schema,
) -> None:
    claim_id = "claim-relationship-only"
    old_attempt = "attempt:v2:relationship-only"
    event_id = "event-relationship-only"
    route = _derive_route(
        claim_id=claim_id,
        predicate="KNOWS",
        fact_kind="explicit_fact",
        object_type="person",
        object_value="Alice",
        object_entity_id="person:alice",
    )
    assert route.disposition.value == "not_applicable"
    assert route.reason_code == "relationship_only"
    await _seed_claim(
        l2_store_with_schema,
        claim_id=claim_id,
        predicate="KNOWS",
        fact_kind="explicit_fact",
        object_type="person",
        object_value="Alice",
        object_entity_id="person:alice",
        user_id="u1",
        subject_ref="user:u1",
        subject_type="user",
        evidence_event_id=event_id,
        created_at=10.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=old_attempt,
        outcome=route.disposition.value,
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        target_id="predicate:KNOWS",
        target_slot_key=None,
        details=_route_details(route),
        reason_code=route.reason_code,
        created_at=11.0,
    )
    triple_id, relationship_slot_key = await _seed_relationship_target(
        l2_store_with_schema,
        predicate="KNOWS",
        object_id="person:alice",
        object_type="person",
        evidence_event_ids=[event_id],
    )
    old_receipt_id = await _seed_target_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=old_attempt,
        target_kind="relationship",
        target_id=triple_id,
        target_slot_key=relationship_slot_key,
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        created_at=12.0,
    )

    first = await reproject_stale_claim_routes(l2_store_with_schema)
    second = await reproject_stale_claim_routes(l2_store_with_schema)

    assert first.not_applicable == 1
    assert first.target_outcomes_invalidated == 1
    assert first.target_outcomes_revalidated == 1
    assert first.targets_archived == 0
    assert second.candidates_selected == 0
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT outcome_id, route_contract_version, reason_code,
                   invalidated_at, invalidated_reason
            FROM l2_claim_projection_outcomes
            WHERE claim_id = ? AND target_kind = 'relationship'
            ORDER BY route_contract_version, created_at
            """,
            (claim_id,),
        ) as cursor:
            receipt_rows = await cursor.fetchall()
    assert len(receipt_rows) == 2
    assert receipt_rows[0]["outcome_id"] == old_receipt_id
    assert receipt_rows[0]["invalidated_reason"] == "route_contract_revalidated"
    assert receipt_rows[1]["route_contract_version"] == ROUTE_CONTRACT_VERSION
    assert receipt_rows[1]["reason_code"] == "route_contract_revalidated"
    assert receipt_rows[1]["invalidated_at"] is None
    assert {
        row["triple_id"]
        for row in await l2_store_with_schema.list_current_relationships(subject_id="user:u1")
    } == {triple_id}


@pytest.mark.asyncio
async def test_route_upgrade_preserves_independent_authority_without_claim_evidence(
    l2_store_with_schema,
) -> None:
    claim_id = "claim-invalid-authority"
    attempt_key = "attempt:v2:invalid-authority"
    claim_event_id = "event-invalid-authority"
    manual_event_id = "event-manual-correction"
    prior_route = _derive_route(
        claim_id=claim_id,
        predicate="BIRTH_DATE",
        fact_kind="explicit_fact",
        object_type="concept",
        object_value="1990-02-03",
    )
    assert prior_route.slot_key is not None
    await _seed_claim(
        l2_store_with_schema,
        claim_id=claim_id,
        predicate="BIRTH_DATE",
        fact_kind="stable_preference",
        object_type="concept",
        object_value="1990-02-03",
        user_id="u1",
        subject_ref="user:u1",
        subject_type="user",
        evidence_event_id=claim_event_id,
        created_at=10.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=attempt_key,
        outcome="routed",
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        target_id=prior_route.route_key,
        target_slot_key=prior_route.slot_key,
        details=_route_details(prior_route),
        created_at=11.0,
    )
    assertion_id = await _seed_assertion_target(
        l2_store_with_schema,
        slot_key=prior_route.slot_key,
        family="identity_profile",
        trait_name="identity.birth_date",
        trait_value="1990-02-03",
        evidence_event_ids=[claim_event_id, manual_event_id],
        authority_ref="correction:assertion",
    )
    triple_id, relationship_slot_key = await _seed_relationship_target(
        l2_store_with_schema,
        predicate="BIRTH_DATE",
        object_id="concept:1990-02-03",
        object_type="concept",
        evidence_event_ids=[claim_event_id, manual_event_id],
        authority_ref="correction:relationship",
    )
    for target_kind, target_id, target_slot_key in (
        ("assertion", assertion_id, prior_route.slot_key),
        ("relationship", triple_id, relationship_slot_key),
    ):
        await _seed_target_outcome(
            l2_store_with_schema,
            claim_id=claim_id,
            attempt_key=attempt_key,
            target_kind=target_kind,
            target_id=target_id,
            target_slot_key=target_slot_key,
            route_contract_version=ROUTE_CONTRACT_VERSION - 1,
            created_at=12.0,
        )

    result = await reproject_stale_claim_routes(l2_store_with_schema)

    assert result.target_outcomes_invalidated == 2
    assert result.targets_archived == 0
    assert result.authority_targets_preserved == 2
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT status, evidence_events FROM tom_trait_assertions WHERE assertion_id = ?",
            (assertion_id,),
        ) as cursor:
            assertion_row = await cursor.fetchone()
        async with db.execute(
            "SELECT status, evidence_event_ids FROM knowledge_graph WHERE triple_id = ?",
            (triple_id,),
        ) as cursor:
            relationship_row = await cursor.fetchone()
    assert assertion_row is not None and assertion_row["status"] != "archived"
    assert json.loads(assertion_row["evidence_events"]) == [manual_event_id]
    assert relationship_row is not None and relationship_row["status"] == "active"
    assert json.loads(relationship_row["evidence_event_ids"]) == [manual_event_id]


@pytest.mark.asyncio
async def test_reprojection_rolls_back_and_recovers_target_retirement(
    l2_store_with_schema,
) -> None:
    claim_id = "claim-rollback"
    attempt_key = "attempt:v2:rollback"
    event_id = "event-rollback"
    prior_route = _derive_route(
        claim_id=claim_id,
        predicate="BIRTH_DATE",
        fact_kind="explicit_fact",
        object_type="concept",
        object_value="1990-02-03",
    )
    assert prior_route.slot_key is not None
    await _seed_claim(
        l2_store_with_schema,
        claim_id=claim_id,
        predicate="BIRTH_DATE",
        fact_kind="stable_preference",
        object_type="concept",
        object_value="1990-02-03",
        evidence_event_id=event_id,
        created_at=10.0,
    )
    await _seed_route_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=attempt_key,
        outcome="routed",
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        target_id=prior_route.route_key,
        target_slot_key=prior_route.slot_key,
        details=_route_details(prior_route),
        created_at=11.0,
    )
    assertion_id = await _seed_assertion_target(
        l2_store_with_schema,
        slot_key=prior_route.slot_key,
        family="identity_profile",
        trait_name="identity.birth_date",
        trait_value="1990-02-03",
        evidence_event_ids=[event_id],
    )
    receipt_id = await _seed_target_outcome(
        l2_store_with_schema,
        claim_id=claim_id,
        attempt_key=attempt_key,
        target_kind="assertion",
        target_id=assertion_id,
        target_slot_key=prior_route.slot_key,
        route_contract_version=ROUTE_CONTRACT_VERSION - 1,
        created_at=12.0,
    )

    with patch(
        "magi.memory.l2.claims.reprojection_write._archive_target",
        side_effect=RuntimeError("retirement failed"),
    ):
        failed = await reproject_stale_claim_routes(l2_store_with_schema)

    assert failed.candidates_selected == 1
    assert failed.failed == 1
    history_after_failure = await l2_store_with_schema.list_claim_projection_outcomes(
        claim_id=claim_id
    )
    assert [
        row["route_contract_version"]
        for row in history_after_failure
        if row["target_kind"] == "route"
    ] == [ROUTE_CONTRACT_VERSION - 1]
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT invalidated_at FROM l2_claim_projection_outcomes WHERE outcome_id = ?",
            (receipt_id,),
        ) as cursor:
            receipt_after_failure = await cursor.fetchone()
        async with db.execute(
            "SELECT status FROM tom_trait_assertions WHERE assertion_id = ?",
            (assertion_id,),
        ) as cursor:
            assertion_after_failure = await cursor.fetchone()
    assert receipt_after_failure is not None
    assert receipt_after_failure["invalidated_at"] is None
    assert assertion_after_failure is not None
    assert assertion_after_failure["status"] != "archived"

    recovered = await reproject_stale_claim_routes(l2_store_with_schema)
    stable = await reproject_stale_claim_routes(l2_store_with_schema)

    assert recovered.failed == 0
    assert recovered.outcomes_appended == 1
    assert recovered.target_outcomes_invalidated == 1
    assert recovered.targets_archived == 1
    assert stable.candidates_selected == 0


@pytest.mark.asyncio
async def test_reprojection_api_rejects_caller_owned_contract_version(
    l2_store_with_schema,
) -> None:
    with pytest.raises(TypeError):
        await reproject_stale_claim_routes(
            l2_store_with_schema,
            route_contract_version=ROUTE_CONTRACT_VERSION + 100,  # type: ignore[call-arg]
        )
    assert not hasattr(
        l2_store_with_schema,
        "append_reprojected_claim_route_outcome",
    )
