"""Preference projections preserve identity, conflict, and historical boundaries."""

from __future__ import annotations

import asyncio
import json
import time

import aiosqlite
import pytest

from magi.events.events import EventLevel, EventTypes
from magi.memory.l2.claims.identity import projection_outcome_id
from magi.memory.l2.claims.reprojection_write import reproject_claim_route
from magi.memory.l2.semantic_routing import ROUTE_CONTRACT_VERSION
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from .test_claim_text_pipeline import APPLE_ID, _entity, _response
from .test_preference_exclusions import _open, _read, _say


def _claim_response(
    event_id,
    text,
    *,
    target=APPLE_ID,
    negative=False,
    predicate="LIKES",
    raw="",
    cue="unspecified",
    text_target=False,
    calendar_expression=None,
):
    result = json.loads(
        _response(
            event_id=event_id,
            object_ref=target,
            evidence=text,
            entities=[]
            if text_target
            else [_entity("苹果", "苹果", "other", resolved_id=APPLE_ID)],
            predicate=predicate,
            polarity="negative" if negative else "positive",
            raw_time_expression=raw,
            temporal_cue=cue,
            calendar_expression=calendar_expression,
            object_type="concept" if text_target else "other",
            fact_kind="stable_preference",
        )
    )
    if text_target:
        result["fact_claims"][0]["specificity"] = "underspecified"
    return result


async def _ingest_response(store, adapter, event_id, text, response):
    adapter._responses = [json.dumps(response, ensure_ascii=False)]
    adapter._fallback_response = "{}"
    before = store.get_l2_pipeline_stats()["extract_completed"]
    await store.ingest_event(
        {
            "id": event_id,
            "type": EventTypes.USER_MESSAGE,
            "timestamp": time.time(),
            "source": "chat",
            "level": EventLevel.INFO.value,
            "data": {
                "user_id": "u1",
                "session_id": f"s-{event_id}",
                "content": text,
                "metadata": {"_temporal": {"calendar_timezone_id": "Asia/Shanghai"}},
            },
        }
    )
    for _ in range(800):
        stats = store.get_l2_pipeline_stats()
        if stats["extract_completed"] > before or stats["extract_failed"]:
            break
        await asyncio.sleep(0.01)
    assert stats["extract_failed"] == 0
    assert stats["extract_completed"] == before + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse_order", [False, True])
async def test_same_occurrence_conflict_stays_deferred_through_route_replay(
    tmp_path, reverse_order
):
    store, adapter = await _open(tmp_path)
    try:
        text = "我之前喜欢苹果，但现在不再喜欢苹果了"
        data = _claim_response("mixed", "我之前喜欢苹果", raw="之前")
        data["fact_claims"][0]["fact_kind"] = "explicit_fact"
        data["fact_claims"].append(
            _claim_response("mixed", "现在不再喜欢苹果了", negative=True, raw="现在", cue="recent", calendar_expression={"kind": "at_observation"})[
                "fact_claims"
            ][0]
        )
        if reverse_order:
            data["fact_claims"].reverse()
        await _ingest_response(store, adapter, "mixed", text, data)
        positive = next(
            claim
            for claim in await store.l2.list_grounded_claims()
            if claim["polarity"] == "positive"
        )
        for _ in range(2):
            result = await reproject_claim_route(store.l2.db_path, claim_id=positive["claim_id"])
            assert result.decision.reason_code == "same_occurrence_preference_conflict"
            assert not result.decision.projection_targets
        assert not await store.l2.list_current_assertions(entity_id="user:u1")
        assert not (await UserPortraitProjectionBuilder(store.l2).build("u1")).prompt_summary
        assert not await _read(store, "SELECT * FROM knowledge_graph")
        negative = next(
            claim
            for claim in await store.l2.list_grounded_claims()
            if claim["polarity"] == "negative"
        )
        async with aiosqlite.connect(store.l2.db_path) as db:
            await db.execute(
                "UPDATE l2_claim_entity_refs SET invalidated_at = ?, invalidated_reason = 'entity_retired' WHERE claim_id = ? AND ref_role = 'object'",
                (time.time(), negative["claim_id"]),
            )
            await db.commit()
        released = await reproject_claim_route(store.l2.db_path, claim_id=positive["claim_id"])
        assert released.decision.reason_code == "unresolved_preference_fact_time"
        assert not released.decision.projection_targets
        replay = await reproject_claim_route(store.l2.db_path, claim_id=positive["claim_id"])
        assert not replay.route_outcome_appended
        routes = await _read(
            store,
            "SELECT * FROM l2_claim_projection_outcomes WHERE claim_id = ? AND target_kind = 'route'",
            (positive["claim_id"],),
        )
        assert len(routes) == 3
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("predicate, phrase", [("LIKES", "喜欢"), ("DISLIKES", "讨厌")])
async def test_exact_text_target_can_be_withdrawn_and_restored(tmp_path, predicate, phrase):
    store, adapter = await _open(tmp_path)
    try:
        positive = f"我{phrase}安静的地方"
        await _ingest_response(
            store,
            adapter,
            "text-positive",
            positive,
            _claim_response(
                "text-positive",
                positive,
                target="安静的地方",
                predicate=predicate,
                text_target=True,
            ),
        )
        original = (await store.l2.list_current_assertions(entity_id="user:u1"))[0]
        negative = f"我已经不再{phrase}安静的地方"
        await _ingest_response(
            store,
            adapter,
            "text-negative",
            negative,
            _claim_response(
                "text-negative",
                negative,
                target="安静的地方",
                predicate=predicate,
                text_target=True,
                negative=True,
            ),
        )
        assert not await store.l2.list_current_assertions(entity_id="user:u1")
        assert not (await UserPortraitProjectionBuilder(store.l2).build("u1")).prompt_summary
        await store.forget_source_events(["text-negative"])
        restored = await store.l2.list_current_assertions(entity_id="user:u1")
        assert len(restored) == 1 and restored[0]["assertion_id"] == original["assertion_id"]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_resolved_historical_interval_survives_projection_and_later_same_value(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        text = "我在2020年9月一直喜欢苹果"
        await _ingest_response(
            store,
            adapter,
            "past",
            text,
            _claim_response(
                "past",
                text,
                raw="2020年9月",
                cue="stable",
                calendar_expression={"kind": "absolute", "unit": "month", "year": 2020, "month": 9},
            ),
        )
        claim = (await store.l2.list_grounded_claims())[0]
        old = (await _read(store, "SELECT * FROM tom_trait_assertions"))[0]
        assert (old["valid_from"], old["valid_to"]) == (
            claim["fact_valid_from"],
            claim["fact_valid_to"],
        )
        assert not await store.l2.list_current_assertions(entity_id="user:u1")
        history = await store.l2.list_current_assertions(
            entity_id="user:u1", effective_at=(old["valid_from"] + old["valid_to"]) / 2
        )
        assert len(history) == 1
        await _say(store, adapter, "current")
        current = await store.l2.list_current_assertions(entity_id="user:u1")
        assert len(current) == 1 and current[0]["assertion_id"] != old["assertion_id"]
        rows = await _read(
            store,
            "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
            (old["assertion_id"],),
        )
        assert rows[0]["valid_to"] == old["valid_to"]
        assert current[0]["evidence_events"] == ["current"]
        await _ingest_response(
            store,
            adapter,
            "past-again",
            text,
            _claim_response(
                "past-again",
                text,
                raw="2020年9月",
                cue="stable",
                calendar_expression={"kind": "absolute", "unit": "month", "year": 2020, "month": 9},
            ),
        )
        after = await store.l2.list_current_assertions(entity_id="user:u1")
        assert len(after) == 1 and after[0]["assertion_id"] == current[0]["assertion_id"]
        assert after[0]["evidence_events"] == ["current"]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("end_successor", [False, True])
async def test_public_forget_cannot_extend_old_preference_across_successor(tmp_path, end_successor):
    store, adapter = await _open(tmp_path)
    try:
        now = time.time()
        await _say(store, adapter, "old-like", observed_at=now - 500)
        await _say(store, adapter, "early-not-like", negative=True, observed_at=now - 400)
        await _say(store, adapter, "successor", predicate="DISLIKES", observed_at=now - 300)
        await _say(store, adapter, "late-not-like", negative=True, observed_at=now - 200)
        if end_successor:
            await _say(
                store,
                adapter,
                "end-successor",
                negative=True,
                predicate="DISLIKES",
                observed_at=now - 100,
            )
        await store.forget_source_events(["early-not-like"])
        for _ in range(2):
            current = await store.l2.list_current_assertions(
                entity_id="user:u1", effective_at=now - 250
            )
            assert len(current) == 1 and current[0]["trait_value"] == "dislike"
            await store.forget_source_events(["early-not-like"])
        await store.forget_source_events(["late-not-like"])
        history = await store.l2.list_current_assertions(
            entity_id="user:u1", effective_at=now - 250
        )
        assert len(history) == 1 and history[0]["trait_value"] == "dislike"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_same_occurrence_explicit_past_and_present_negation_keep_history(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        positive = "我在2020年9月喜欢苹果"
        negative = "现在不再喜欢苹果了"
        data = _claim_response(
            "dated-mixed",
            positive,
            raw="2020年9月",
            cue="stable",
            calendar_expression={"kind": "absolute", "unit": "month", "year": 2020, "month": 9},
        )
        data["fact_claims"].append(
            _claim_response(
                "dated-mixed",
                negative,
                negative=True,
                raw="现在",
                cue="recent",
                calendar_expression={"kind": "at_observation"},
            )["fact_claims"][0]
        )
        await _ingest_response(store, adapter, "dated-mixed", positive + "，但" + negative, data)
        assert not await store.l2.list_current_assertions(entity_id="user:u1")
        rows = await _read(store, "SELECT * FROM tom_trait_assertions")
        assert len(rows) == 1 and rows[0]["valid_to"] < time.time()
        history = await store.l2.list_current_assertions(
            entity_id="user:u1",
            effective_at=(rows[0]["valid_from"] + rows[0]["valid_to"]) / 2,
        )
        assert len(history) == 1 and history[0]["trait_value"] == "like"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_later_same_value_reaffirmation_does_not_fill_withdrawn_interval(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        now = time.time()
        await _say(store, adapter, "old-positive", observed_at=now - 300)
        await _say(store, adapter, "withdrawal", negative=True, observed_at=now - 200)
        await _say(store, adapter, "reaffirmed", observed_at=now - 100)
        assert not await store.l2.list_current_assertions(
            entity_id="user:u1", effective_at=now - 150
        )
        current = await store.l2.list_current_assertions(entity_id="user:u1")
        assert len(current) == 1 and current[0]["valid_from"] == now - 100
        assert (
            len(await store.l2.list_current_assertions(entity_id="user:u1", effective_at=now - 250))
            == 1
        )
        before_ids = {
            row["assertion_id"]
            for row in await _read(store, "SELECT assertion_id FROM tom_trait_assertions")
        }
        duplicate = await store.ingest_event(
            {
                "id": "reaffirmed",
                "type": EventTypes.USER_MESSAGE,
                "timestamp": now - 100,
                "source": "chat",
                "level": EventLevel.INFO.value,
                "data": {
                    "user_id": "u1",
                    "session_id": "session-reaffirmed",
                    "content": "我一直喜欢苹果",
                    "metadata": {"_temporal": {"calendar_timezone_id": "Asia/Shanghai"}},
                },
            }
        )
        assert duplicate["l1_confirmed"]
        jobs = await _read(
            store, "SELECT status FROM l2_projection_jobs WHERE event_id = ?", ("reaffirmed",)
        )
        assert jobs == [{"status": "completed"}]
        assert {
            row["assertion_id"]
            for row in await _read(store, "SELECT assertion_id FROM tom_trait_assertions")
        } == before_ids
        assert not await store.l2.list_current_assertions(
            entity_id="user:u1", effective_at=now - 150
        )
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_route_upgrade_keeps_exclusion_until_all_routes_are_known(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        await _say(store, adapter, "positive", observed_at=time.time() - 100)
        await _say(store, adapter, "negative", negative=True)
        claims = await store.l2.list_grounded_claims()
        positive = next(claim for claim in claims if claim["polarity"] == "positive")
        negative = next(claim for claim in claims if claim["polarity"] == "negative")
        async with aiosqlite.connect(store.l2.db_path) as db:
            await db.execute(
                "UPDATE l2_claim_projection_outcomes SET route_contract_version = ?",
                (ROUTE_CONTRACT_VERSION - 1,),
            )
            async with db.execute(
                "SELECT outcome_id, claim_id, target_id FROM l2_claim_projection_outcomes WHERE target_kind = 'exclusion'"
            ) as cursor:
                legacy_receipts = await cursor.fetchall()
            for outcome_id, claim_id, target_id in legacy_receipts:
                legacy_attempt = f"preference-exclusion:{claim_id}"
                await db.execute(
                    "UPDATE l2_claim_projection_outcomes SET outcome_id = ?, attempt_key = ? WHERE outcome_id = ?",
                    (
                        projection_outcome_id(
                            claim_id=claim_id,
                            attempt_key=legacy_attempt,
                            target_kind="exclusion",
                            target_id=target_id,
                        ),
                        legacy_attempt,
                        outcome_id,
                    ),
                )
            await db.commit()
        await reproject_claim_route(store.l2.db_path, claim_id=positive["claim_id"])
        assert not await store.l2.list_current_assertions(entity_id="user:u1")
        assert len(await _read(store, "SELECT * FROM l2_preference_exclusion_effects")) == 2
        await reproject_claim_route(store.l2.db_path, claim_id=negative["claim_id"])
        assert not await store.l2.list_current_assertions(entity_id="user:u1")
        await store.forget_source_events(["negative"])
        restored = await store.l2.list_current_assertions(entity_id="user:u1")
        assert len(restored) == 1 and restored[0]["trait_value"] == "like"
    finally:
        await store.shutdown()
