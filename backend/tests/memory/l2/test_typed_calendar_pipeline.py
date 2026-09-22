"""Typed calendar judgments survive real persistence without runtime date inference."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from magi.events.events import EventLevel, EventTypes
from magi.memory.l2.claim_text import persisted_claim_to_phase1
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from .test_claim_text_pipeline import APPLE_ID, _ingest, _open_store, _response
from .test_phase1_entity_grounding import _entity


@pytest.mark.asyncio
@pytest.mark.parametrize(("raw", "meaning", "start", "end"), [
    ("下周一", {"kind": "weekday", "week_offset": 1, "weekday": 0}, (2026, 8, 10), (2026, 8, 11)),
    ("下星期一", {"kind": "weekday", "week_offset": 1, "weekday": 0}, (2026, 8, 10), (2026, 8, 11)),
    ("下月", {"kind": "relative_period", "unit": "month", "offset": 1}, (2026, 9, 1), (2026, 10, 1)),
    ("下个月", {"kind": "relative_period", "unit": "month", "offset": 1}, (2026, 9, 1), (2026, 10, 1)),
    ("明天", None, None, None),
    ("下个月", {"kind": "relative_period", "unit": "month", "offset": 1, "timestamp": 123}, None, None),
])
async def test_calendar_meaning_uses_frozen_source_time_and_survives_restart(tmp_path, raw, meaning, start, end):
    zone = ZoneInfo("Asia/Shanghai")
    anchor = datetime(2026, 8, 3, 12, tzinfo=zone).timestamp()
    evidence = f"我计划{raw}去海边"
    store, adapter = await _open_store(tmp_path, _response(
        event_id="evt-calendar", object_ref="去海边", evidence=evidence, entities=[],
        predicate="PLANS_TO", object_type="activity", fact_kind="future_intent",
        raw_time_expression=raw, calendar_expression=meaning,
    ))
    try:
        await store.ingest_event({
            "id": "evt-calendar", "type": EventTypes.USER_MESSAGE, "timestamp": anchor,
            "source": "chat", "level": EventLevel.INFO.value,
            "data": {
                "user_id": "u1", "session_id": "calendar-session", "content": evidence,
                "metadata": {"_temporal": {"calendar_timezone_id": "Asia/Shanghai"}},
            },
        })
        for _ in range(600):
            stats = store.get_l2_pipeline_stats()
            if stats["extract_completed"] or stats["extract_failed"]:
                break
            await asyncio.sleep(.01)
        assert stats["extract_failed"] == 0
        assert stats["extract_completed"] == 1
        claims = await store.l2.list_grounded_claims()
        assert len(claims) == 1
        claim = claims[0]
        assert claim["raw_time_frame"]["raw"] == raw
        if start is not None:
            assert claim["target_from"] == datetime(*start, tzinfo=zone).timestamp()
            assert claim["target_to"] == datetime(*end, tzinfo=zone).timestamp()
            assert claim["raw_time_frame"]["expression"] == meaning
            assert persisted_claim_to_phase1(claim).calendar_expression.to_dict() == meaning
        else:
            assert claim["target_from"] is None and claim["target_to"] is None
            assert claim["raw_time_frame"]["expression"] is None
            assert claim["raw_time_frame"]["resolution"] == "unresolved_text"
        assert len(adapter.calls) == 1
    finally:
        await store.shutdown()
    reopened, _adapter = await _open_store(tmp_path, "{}")
    try:
        restored = await reopened.l2.get_grounded_claim(claim["claim_id"])
        assert restored["raw_time_frame"] == claim["raw_time_frame"]
        assert restored["target_from"] == claim["target_from"]
        assert restored["target_to"] == claim["target_to"]
    finally:
        await reopened.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("meaning", [None, {"kind": "absolute", "unit": "month", "year": "2020", "month": 9}])
async def test_unresolved_historical_preference_cannot_become_current_memory(tmp_path, meaning):
    text = "我在2020年9月一直喜欢苹果"
    store, _adapter = await _open_store(tmp_path, _response(
        event_id="evt-unresolved-past", object_ref=APPLE_ID, evidence=text,
        entities=[_entity("苹果", "苹果", "other", resolved_id=APPLE_ID)],
        temporal_cue="stable", raw_time_expression="2020年9月", calendar_expression=meaning,
    ))
    try:
        await store.l2_entity_catalog.upsert_entity(entity_id=APPLE_ID, canonical_name="苹果", entity_type="other")
        await _ingest(store, event_id="evt-unresolved-past", content=text)
        claims = await store.l2.list_grounded_claims()
        assert len(claims) == 1
        assert claims[0]["raw_time_frame"]["raw"] == "2020年9月"
        assert claims[0]["raw_time_frame"]["resolution"] == "unresolved_text"
        assert claims[0]["fact_valid_from"] is None and claims[0]["fact_valid_to"] is None
        assert await store.l2.list_current_assertions(entity_id="user:u1") == []
        assert await store.l2.list_current_relationships(subject_id="user:u1") == []
        assert (await UserPortraitProjectionBuilder(store.l2).build("u1")).prompt_summary == []
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["现在", "目前", "此刻"])
async def test_observation_preference_remains_current_without_invented_end(tmp_path, raw):
    text = f"我{raw}喜欢苹果"
    store, _adapter = await _open_store(tmp_path, _response(
        event_id="evt-observation", object_ref=APPLE_ID, evidence=text,
        entities=[_entity("苹果", "苹果", "other", resolved_id=APPLE_ID)],
        temporal_cue="recent", raw_time_expression=raw, calendar_expression={"kind": "at_observation"},
    ))
    try:
        await store.l2_entity_catalog.upsert_entity(entity_id=APPLE_ID, canonical_name="苹果", entity_type="other")
        await _ingest(store, event_id="evt-observation", content=text)
        claims = await store.l2.list_grounded_claims()
        assert len(claims) == 1
        assert claims[0]["raw_time_frame"]["resolution"] == "observation_anchor"
        assert claims[0]["fact_valid_from"] is None and claims[0]["fact_valid_to"] is None
        assertions = await store.l2.list_current_assertions(entity_id="user:u1")
        assert len(assertions) == 1
        assert assertions[0]["valid_to"] is None
        assert (await UserPortraitProjectionBuilder(store.l2).build("u1")).prompt_summary
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_bounded_preference_reaches_current_reads_only_inside_its_day(tmp_path, monkeypatch):
    import time

    zone = ZoneInfo("Asia/Shanghai")
    anchor = datetime(2026, 8, 3, 12, tzinfo=zone).timestamp()
    text = "我今天喜欢苹果"
    store, _adapter = await _open_store(tmp_path, _response(
        event_id="evt-bounded-preference", object_ref=APPLE_ID, evidence=text,
        entities=[_entity("苹果", "苹果", "other", resolved_id=APPLE_ID)],
        temporal_cue="recent", raw_time_expression="今天",
        calendar_expression={"kind": "relative_period", "unit": "day", "offset": 0},
    ))
    try:
        await store.l2_entity_catalog.upsert_entity(entity_id=APPLE_ID, canonical_name="苹果", entity_type="other")
        await store.ingest_event({
            "id": "evt-bounded-preference", "type": EventTypes.USER_MESSAGE, "timestamp": anchor,
            "source": "chat", "level": EventLevel.INFO.value,
            "data": {"user_id": "u1", "session_id": "bounded-day", "content": text,
                "metadata": {"_temporal": {"calendar_timezone_id": "Asia/Shanghai"}}},
        })
        for _ in range(600):
            stats = store.get_l2_pipeline_stats()
            if stats["extract_completed"] or stats["extract_failed"]:
                break
            await asyncio.sleep(.01)
        assert stats["extract_completed"] == 1 and stats["extract_failed"] == 0
        for at, expected in ((anchor, True), (anchor + 86400, False)):
            with monkeypatch.context() as clock:
                clock.setattr(time, "time", lambda: at)
                assertions = await store.l2.list_current_assertions(entity_id="user:u1")
                portrait = await UserPortraitProjectionBuilder(store.l2).build("u1")
                assert bool(assertions) is expected
                assert bool(portrait.prompt_summary) is expected
    finally:
        await store.shutdown()
