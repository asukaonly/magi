"""Grounded Claim lifecycle coverage for entity merge and forget."""

from __future__ import annotations

import json

import aiosqlite
import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.claims.reprojection import reproject_stale_claim_routes
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.entities.maintenance import L2EntityMaintenance
from magi.memory.l2.semantic_routing import (
    ROUTE_CONTRACT_VERSION,
    SemanticRouteInput,
    derive_semantic_route,
)

pytestmark = pytest.mark.asyncio


async def _seed_claim(
    store,  # type: ignore[no-untyped-def]
    *,
    claim_id: str,
    object_entity_id: str,
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
            (claim_id, f"event:{claim_id}"),
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
            ) VALUES (?, ?, 'attempt:seed', 'route', 'route:sensitive',
                      'slot:sensitive', ?, 'routed', 'seed', ?, 10.0)
            """,
            (
                f"outcome:{claim_id}:current",
                claim_id,
                ROUTE_CONTRACT_VERSION,
                json.dumps(
                    {
                        "family": "preference_profile",
                        "value_fingerprint": "value:sensitive",
                    }
                ),
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
