"""Backlog visibility and idempotent Claim route reprojection tests."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.claims.identity import projection_outcome_id
from magi.memory.l2.claims.reprojection import (
    list_unrouted_claim_backlog,
    reproject_stale_claim_routes,
)
from magi.memory.l2.entities.maintenance import L2EntityMaintenance


async def _seed_claim(
    store,  # type: ignore[no-untyped-def]
    *,
    claim_id: str,
    predicate: str,
    created_at: float,
    object_entity_id: str | None = None,
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
                :claim_id, :identity_key, 1, 1, 'attempt:seed', 'test', NULL,
                'person:user', 'person', :predicate, 'explicit_fact',
                'topic', 'positive', 'concrete', 0.9,
                :object_value_json, :object_surface, 'current', 'active',
                :created_at, :created_at
            )
            """,
            {
                "claim_id": claim_id,
                "identity_key": f"identity:{claim_id}",
                "predicate": predicate,
                "object_value_json": json.dumps("Jazz"),
                "object_surface": "Jazz",
                "created_at": created_at,
            },
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
) -> None:
    target_id = f"seed:{claim_id}:{attempt_key}"
    outcome_id = projection_outcome_id(
        claim_id=claim_id,
        attempt_key=attempt_key,
        target_kind="route",
        target_id=target_id,
    )
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO l2_claim_projection_outcomes(
                outcome_id, claim_id, attempt_key, target_kind, target_id,
                route_contract_version, outcome, reason_code, created_at
            ) VALUES (?, ?, ?, 'route', ?, ?, ?, ?, ?)
            """,
            (
                outcome_id,
                claim_id,
                attempt_key,
                target_id,
                route_contract_version,
                outcome,
                "seed",
                created_at,
            ),
        )
        await db.commit()


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
        route_contract_version=0,
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
        route_contract_version=1,
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
        route_contract_version=1,
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
        route_contract_version=2,
        created_at=41.0,
    )

    first = await reproject_stale_claim_routes(
        l2_store_with_schema,
        route_contract_version=1,
    )
    second = await reproject_stale_claim_routes(
        l2_store_with_schema,
        route_contract_version=1,
    )

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
    assert [row["route_contract_version"] for row in old_route_history] == [0, 1]
    assert [row["outcome"] for row in old_route_history] == ["unrouted", "routed"]
    assert old_route_history[-1]["outcome"] == "routed"
    assert old_route_history[-1]["attempt_key"] == ("route-reproject:v1:r1:claim-old-route")
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
        route_contract_version=1,
        created_at=11.0,
    )

    unresolved = await reproject_stale_claim_routes(
        l2_store_with_schema,
        route_contract_version=1,
    )
    unchanged = await reproject_stale_claim_routes(
        l2_store_with_schema,
        route_contract_version=1,
    )
    await _seed_object_ref(
        l2_store_with_schema,
        claim_id="claim-resolves-later",
        entity_id="topic:jazz",
        resolution_version=1,
        created_at=12.0,
    )
    resolved = await reproject_stale_claim_routes(
        l2_store_with_schema,
        route_contract_version=1,
    )
    stable = await reproject_stale_claim_routes(
        l2_store_with_schema,
        route_contract_version=1,
    )

    assert unresolved.candidates_selected == 1
    assert unresolved.outcomes_appended == 1
    assert unresolved.unrouted == 1
    assert unchanged.candidates_selected == 0
    assert resolved.candidates_selected == 1
    assert resolved.outcomes_appended == 1
    assert resolved.routed == 1
    assert stable.candidates_selected == 0

    history = await l2_store_with_schema.list_claim_projection_outcomes(
        claim_id="claim-resolves-later"
    )
    assert len(history) == 3
    assert [row["outcome"] for row in history] == ["unrouted", "unrouted", "routed"]
    assert [row["attempt_key"] for row in history[1:]] == [
        "route-reproject:v1:r0:claim-resolves-later",
        "route-reproject:v1:r1:claim-resolves-later",
    ]


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
        route_contract_version=0,
        created_at=11.0,
    )

    await asyncio.gather(
        reproject_stale_claim_routes(
            l2_store_with_schema,
            route_contract_version=1,
        ),
        reproject_stale_claim_routes(
            l2_store_with_schema,
            route_contract_version=1,
        ),
    )

    history = await l2_store_with_schema.list_claim_projection_outcomes(claim_id="claim-concurrent")
    assert len(history) == 2
    assert [row["route_contract_version"] for row in history] == [0, 1]
    assert history[-1]["attempt_key"] == "route-reproject:v1:r1:claim-concurrent"


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
        route_contract_version=1,
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
        route_contract_version=1,
        groups=stats.unrouted_claim_backlog,
    )
