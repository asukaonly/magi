"""Arrival order cannot change an assertion's factual timeline or evidence."""
from __future__ import annotations

import json
from itertools import permutations
import time

import pytest

from magi.events.events import EventLevel, EventTypes
from magi.memory.l2.corrections.models import CorrectionKind
from .test_preference_exclusions import _open, _read, _say


async def _timeline(store, start):
    result = []
    for offset in (10, 110, 210, 310):
        rows = await store.l2.list_current_assertions(entity_id="user:u1", effective_at=start + offset)
        result.append([row["trait_value"] for row in rows])
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("arrival_order, middle_predicate", [
    ((0, 2, 1), "LIKES"),
    ((2, 0, 1), "LIKES"),
    ((0, 2, 1), "DISLIKES"),
])
async def test_late_observation_matches_chronological_timeline(tmp_path, arrival_order, middle_predicate):
    start = time.time() - 400
    events = [("t1", "LIKES", start), ("t2", middle_predicate, start + 100), ("t3", "DISLIKES", start + 200)]
    timelines = []
    for name, order in (("ordered", (0, 1, 2)), ("late", arrival_order)):
        store, adapter = await _open(tmp_path / name)
        try:
            for index in order:
                event_id, predicate, at = events[index]
                await _say(store, adapter, event_id, predicate=predicate, observed_at=at)
            timelines.append(await _timeline(store, start))
            current = await store.l2.list_current_assertions(entity_id="user:u1")
            assert [row["trait_value"] for row in current] == ["dislike"]
            rows = await _read(store, "SELECT assertion_id, trait_value, valid_from, valid_to, evidence_events FROM tom_trait_assertions")
            expected_predicates = {event_id: predicate for event_id, predicate, _ in events}
            for row in rows:
                assert row["valid_to"] is None or row["valid_from"] < row["valid_to"], row
                assert all(expected_predicates[event] == ("LIKES" if row["trait_value"] == "like" else "DISLIKES")
                           for event in json.loads(row["evidence_events"])), row
            duplicate = await store.ingest_event({
                "id": "t2", "type": EventTypes.USER_MESSAGE, "timestamp": start + 100,
                "source": "chat", "level": EventLevel.INFO.value,
                "data": {"user_id": "u1", "session_id": "session-t2", "content": "重复源事件"},
            })
            assert duplicate["l1_confirmed"]
            assert await _read(store, "SELECT assertion_id, trait_value, valid_from, valid_to, evidence_events FROM tom_trait_assertions") == rows
            assert await _timeline(store, start) == timelines[-1]
        finally:
            await store.shutdown()
    assert timelines[0] == timelines[1]
    assert timelines[0] == [["like"], ["like" if middle_predicate == "LIKES" else "dislike"], ["dislike"], ["dislike"]]


@pytest.mark.asyncio
async def test_late_conflicting_observation_respects_explicit_user_correction(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        now = time.time()
        await _say(store, adapter, "original", observed_at=now - 100)
        original = (await store.l2.list_current_assertions(entity_id="user:u1"))[0]
        correction = await store.l2.apply_assertion_correction(
            assertion_id=original["assertion_id"], request_id="correct-order", actor_id="user:u1", reason="That preference was incorrect",
            correction_kind=CorrectionKind.RECORD_ERROR, replacement_value="dislike",
        )
        assert correction is not None
        await _say(store, adapter, "late-older", observed_at=now - 300)
        current = await store.l2.list_current_assertions(entity_id="user:u1")
        assert [row["trait_value"] for row in current] == ["dislike"]
        assert current[0]["authority_ref"]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_late_support_keeps_negative_closure_reversible(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        now = time.time()
        await _say(store, adapter, "t1", observed_at=now - 400)
        await _say(store, adapter, "withdrawal", negative=True, observed_at=now - 200)
        await _say(store, adapter, "successor", predicate="DISLIKES", observed_at=now - 100)
        await _say(store, adapter, "late-t2", observed_at=now - 300)
        assert not await store.l2.list_current_assertions(entity_id="user:u1", effective_at=now - 150)
        await store.forget_source_events(["withdrawal"])
        restored = await store.l2.list_current_assertions(entity_id="user:u1", effective_at=now - 150)
        assert [row["trait_value"] for row in restored] == ["like"]
        assert [row["trait_value"] for row in await store.l2.list_current_assertions(entity_id="user:u1")] == ["dislike"]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("order", list(permutations(range(3))))
@pytest.mark.parametrize("sequence", ["LDL", "LLD", "LNL"])
async def test_all_three_observation_permutations_preserve_fact_and_evidence(tmp_path, order, sequence):
    store, adapter = await _open(tmp_path)
    try:
        start = time.time() - 400
        for index in order:
            action = sequence[index]
            await _say(store, adapter, f"t{index}", predicate="DISLIKES" if action == "D" else "LIKES",
                       negative=action == "N", observed_at=start + index * 100)
        expected = {"L": ["like"], "D": ["dislike"], "N": []}
        for index, action in enumerate(sequence):
            rows = await store.l2.list_current_assertions(entity_id="user:u1", effective_at=start + index * 100 + 50)
            assert [row["trait_value"] for row in rows] == expected[action], (order, sequence, index, rows)
            for row in rows:
                evidence = row["evidence_events"]
                assert all(sequence[int(event[1:])] == ("L" if row["trait_value"] == "like" else "D") for event in evidence)
                assert all(start + int(event[1:]) * 100 >= row["valid_from"] for event in evidence), row
                assert all(row["valid_to"] is None or start + int(event[1:]) * 100 < row["valid_to"] for event in evidence), row
        if "N" in sequence:
            await store.forget_source_events(["t1"])
            restored = await store.l2.list_current_assertions(entity_id="user:u1", effective_at=start + 150)
            assert [row["trait_value"] for row in restored] == ["like"]
        claims = await store.l2.list_grounded_claims()
        from magi.memory.l2.claims.reprojection_write import reproject_claim_route
        for _ in range(2):
            for claim in claims:
                await reproject_claim_route(store.l2.db_path, claim_id=claim["claim_id"])
        for index, action in enumerate(sequence):
            rows = await store.l2.list_current_assertions(entity_id="user:u1", effective_at=start + index * 100 + 50)
            assert [row["trait_value"] for row in rows] == (["like"] if action == "N" else expected[action])
        bindings = await _read(store, """SELECT evidence.event_id, evidence.event_time, assertion.valid_from, assertion.valid_to, assertion.evidence_events
            FROM l2_claim_projection_outcomes receipt
            JOIN tom_trait_assertions assertion ON assertion.assertion_id = receipt.target_id
            JOIN l2_claim_evidence evidence ON evidence.claim_id = receipt.claim_id AND evidence.link_role = 'supporting'
            WHERE receipt.target_kind = 'assertion' AND receipt.outcome = 'projected' AND receipt.invalidated_at IS NULL""")
        for binding in bindings:
            assert binding["event_id"] in json.loads(binding["evidence_events"]), binding
            assert binding["valid_from"] <= binding["event_time"], binding
            assert binding["valid_to"] is None or binding["event_time"] < binding["valid_to"], binding
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_observation_rebuild_preserves_calendar_bounded_assertion_identity(tmp_path):
    from .test_preference_lifecycle import _claim_response, _ingest_response
    store, adapter = await _open(tmp_path)
    try:
        text = "我在2020年9月喜欢苹果"
        await _ingest_response(store, adapter, "calendar", text, _claim_response(
            "calendar", text, raw="2020年9月", cue="stable",
            calendar_expression={"kind": "absolute", "unit": "month", "year": 2020, "month": 9},
        ))
        before = (await _read(store, "SELECT assertion_id, valid_from, valid_to FROM tom_trait_assertions"))[0]
        await _say(store, adapter, "current", predicate="DISLIKES")
        after = (await _read(store, "SELECT assertion_id, valid_from, valid_to FROM tom_trait_assertions WHERE assertion_id = ?", (before["assertion_id"],)))[0]
        assert after == before
        history = await store.l2.list_current_assertions(entity_id="user:u1", effective_at=(before["valid_from"] + before["valid_to"]) / 2)
        assert [row["assertion_id"] for row in history] == [before["assertion_id"]]
        assert [row["trait_value"] for row in await store.l2.list_current_assertions(entity_id="user:u1")] == ["dislike"]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("predicates", [("LIKES", "DISLIKES"), ("DISLIKES", "LIKES")])
@pytest.mark.parametrize("with_history", [False, True])
async def test_simultaneous_conflict_is_unknown_in_both_arrival_orders(tmp_path, predicates, with_history):
    from magi.memory.l2.claims.reprojection_write import reproject_claim_route
    from .test_preference_exclusions import _reconcile
    store, adapter = await _open(tmp_path)
    try:
        at = time.time() - 100
        if with_history:
            await _say(store, adapter, "past", observed_at=at - 100)
        for index, predicate in enumerate(predicates):
            await _say(store, adapter, f"same-{index}", predicate=predicate, observed_at=at)
        assert not await store.l2.list_current_assertions(entity_id="user:u1")
        if with_history:
            history = await store.l2.list_current_assertions(entity_id="user:u1", effective_at=at - 50)
            assert [row["trait_value"] for row in history] == ["like"]
        skipped = await _read(store, "SELECT * FROM l2_claim_projection_outcomes WHERE target_kind = 'assertion' AND outcome = 'skipped'")
        assert any(row["reason_code"] == "ambiguous_observation_time" for row in skipped)
        for claim in await store.l2.list_grounded_claims():
            await reproject_claim_route(store.l2.db_path, claim_id=claim["claim_id"])
        assert not await store.l2.list_current_assertions(entity_id="user:u1")
        await store.forget_source_events(["same-1"])
        await _reconcile(store)
        current = await store.l2.list_current_assertions(entity_id="user:u1")
        assert [row["trait_value"] for row in current] == ["like" if predicates[0] == "LIKES" else "dislike"]
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_timeline_rebuild_preserves_evidence_span_for_stable_promotion(tmp_path):
    from .test_preference_exclusions import _reconcile
    store, adapter = await _open(tmp_path)
    try:
        now = time.time()
        for index, days in enumerate((4, 2, 0)):
            await _say(store, adapter, f"day-{index}", observed_at=now - days * 86400)
        before = (await store.l2.list_current_assertions(entity_id="user:u1"))[0]
        assert before["validation_state"] == "stable"
        await _reconcile(store)
        after = (await store.l2.list_current_assertions(entity_id="user:u1"))[0]
        assert after["validation_state"] == "stable"
        assert after["first_inferred_at"] == now - 4 * 86400
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_repeated_withdrawal_forgetting_rebinds_live_receipts_idempotently(tmp_path):
    from magi.memory.l2.claims.reprojection_write import reproject_claim_route
    from .test_preference_exclusions import _reconcile
    store, adapter = await _open(tmp_path)
    try:
        start = time.time() - 600
        await _say(store, adapter, "early", observed_at=start)
        await _say(store, adapter, "late", observed_at=start + 300)
        restored_ids = []
        for index, offset in enumerate((100, 200)):
            negative = f"withdraw-{index}"
            await _say(store, adapter, negative, negative=True, observed_at=start + offset)
            assert not await store.l2.list_current_assertions(entity_id="user:u1", effective_at=start + 250)
            assert [row["trait_value"] for row in await store.l2.list_current_assertions(entity_id="user:u1")] == ["like"]
            await store.forget_source_events([negative])
            restored = await store.l2.list_current_assertions(entity_id="user:u1", effective_at=start + 250)
            assert [row["trait_value"] for row in restored] == ["like"]
            restored_ids.append(restored[0]["assertion_id"])
        assert len(set(restored_ids)) == 1
        claims = await store.l2.list_grounded_claims()
        for claim in claims:
            await reproject_claim_route(store.l2.db_path, claim_id=claim["claim_id"])
        before = await _read(store, "SELECT outcome_id FROM l2_claim_projection_outcomes WHERE invalidated_at IS NULL ORDER BY outcome_id")
        for claim in claims:
            await reproject_claim_route(store.l2.db_path, claim_id=claim["claim_id"])
        after = await _read(store, "SELECT outcome_id FROM l2_claim_projection_outcomes WHERE invalidated_at IS NULL ORDER BY outcome_id")
        assert after == before
        for event in ("early", "late"):
            receipts = await _read(store, """SELECT DISTINCT receipt.target_id FROM l2_claim_projection_outcomes receipt
                JOIN l2_claim_evidence evidence ON evidence.claim_id = receipt.claim_id
                WHERE receipt.target_kind = 'assertion' AND receipt.outcome = 'projected'
                  AND receipt.invalidated_at IS NULL AND evidence.event_id = ?""", (event,))
            assert receipts == [{"target_id": restored_ids[-1]}]
        await store.forget_source_events(["early"])
        await _reconcile(store)
        current = await store.l2.list_current_assertions(entity_id="user:u1")
        assert len(current) == 1 and current[0]["evidence_events"] == ["late"]
        assert current[0]["valid_from"] == start + 300
    finally:
        await store.shutdown()
