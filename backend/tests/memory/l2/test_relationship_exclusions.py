"""Direct current-state denials close only supported enduring relationships."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from magi.memory.l2.claims.reprojection_write import reproject_claim_route
from magi.memory.l2.corrections.models import CorrectionKind
from magi.memory.l2.semantic_routing import ProjectionTarget, derive_semantic_route

from .test_claim_text_pipeline import _entity, _open_store, _response
from .test_preference_exclusions import _read, _reconcile
from .test_semantic_routing import _route_input


RELATIONSHIPS = [
    ("LIVES_IN", "place", "上海", "住在"),
    ("WORKS_AT", "organization", "某公司", "就职于"),
    ("MEMBER_OF", "group", "研究组", "属于"),
    ("OWNS", "other", "这台电脑", "拥有"),
    ("WORKS_WITH", "person", "小林", "合作于"),
    ("USES", "software", "编辑器", "使用"),
    ("FOLLOWS", "person", "这位创作者", "关注"),
    ("PROFICIENT_IN", "skill", "Python", "擅长"),
]
TARGET_ID = "entity:current-state-target"


async def _say_relation(
    store, adapter, event_id, *, at, relation=RELATIONSHIPS[0], negative=False,
    raw="", cue="unspecified", evidence_mode="direct", assertion_mode="asserted",
    calendar_expression=None, contradictory=False,
):
    predicate, object_type, name, verb = relation
    await store.l2_entity_catalog.upsert_entity(
        entity_id=TARGET_ID, canonical_name=name, entity_type=object_type,
    )
    content = f'我{raw}{"不再" if negative else "一直"}{verb}{name}。'
    payload = json.loads(_response(
        event_id=event_id, object_ref=TARGET_ID, object_type=object_type,
        fact_kind="explicit_fact", evidence=content,
        entities=[_entity(name, name, object_type, resolved_id=TARGET_ID)],
        predicate=predicate, polarity="negative" if negative else "positive",
        temporal_cue=cue, raw_time_expression=raw,
        calendar_expression=calendar_expression, evidence_mode=evidence_mode,
    ))
    payload["fact_claims"][0]["assertion_mode"] = assertion_mode
    if contradictory:
        payload["fact_claims"].append({**payload["fact_claims"][0], "polarity": "negative"})
    adapter._responses = [json.dumps(payload, ensure_ascii=False)]
    before = store.get_l2_pipeline_stats()["extract_completed"]
    result = await store.ingest_event({
        "id": event_id, "type": "UserMessage", "timestamp": at, "source": "chat", "level": 1,
        "data": {"user_id": "u1", "session_id": event_id, "content": content},
    })
    assert result["l2_job_enqueued"]
    for _ in range(800):
        stats = store.get_l2_pipeline_stats()
        if stats["extract_completed"] > before or stats["extract_failed"]:
            break
        await asyncio.sleep(0.01)
    assert stats["extract_failed"] == 0, stats
    assert stats["extract_completed"] == before + 1, stats


async def _current(store, *, at=None):
    return await store.l2.list_current_relationships(
        subject_id="user:u1", object_id=TARGET_ID, effective_at=at,
    )


@pytest.fixture
async def relationship_memory(tmp_path):
    store, adapter = await _open_store(tmp_path, "{}")
    try:
        yield store, adapter
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("relation", RELATIONSHIPS, ids=[row[0] for row in RELATIONSHIPS])
async def test_direct_denial_preserves_past_and_reaffirmation_gap(relationship_memory, relation):
    store, adapter = relationship_memory
    first = time.time() - 300
    cutoff, again = first + 100, first + 200
    await _say_relation(store, adapter, "first", relation=relation, at=first)
    assert len(await _current(store)) == 1
    await _say_relation(store, adapter, "withdrawal", relation=relation, at=cutoff, negative=True)
    assert await _current(store) == []
    historical = await _current(store, at=first + 1)
    assert [(row["predicate"], row["valid_to"]) for row in historical] == [(relation[0], cutoff)]
    assert historical[0]["evidence_event_ids"] == ["first"]
    negative = next(c for c in await store.l2.list_grounded_claims() if c["polarity"] == "negative")
    for _ in range(2):
        result = await reproject_claim_route(store.l2.db_path, claim_id=negative["claim_id"])
        assert ProjectionTarget.EXCLUSION in result.decision.projection_targets
        assert not await _current(store)
    effects = await _read(store, "SELECT * FROM l2_claim_projection_outcomes WHERE target_kind = 'exclusion'")
    assert len(effects) == 1 and effects[0]["reason_code"] == "explicit_relationship_negation"
    await _say_relation(store, adapter, "again", relation=relation, at=again)
    current = await _current(store)
    assert [(row["predicate"], row["valid_from"], row["evidence_event_ids"]) for row in current] == [
        (relation[0], again, ["again"]),
    ]
    assert not await _current(store, at=cutoff + 1)
    assert (await _current(store, at=first + 1))[0]["valid_to"] == cutoff


@pytest.mark.asyncio
@pytest.mark.parametrize("forget_positive", [False, True])
async def test_forgetting_denial_restores_only_independently_supported_relationship(
    relationship_memory, forget_positive,
):
    store, adapter = relationship_memory
    first = time.time() - 300
    await _say_relation(store, adapter, "first", at=first)
    await _say_relation(store, adapter, "withdrawal", at=first + 100, negative=True)
    negative = next(c for c in await store.l2.list_grounded_claims() if c["polarity"] == "negative")
    await store.forget_source_events(["withdrawal", "first"] if forget_positive else ["withdrawal"])
    await _reconcile(store)
    assert len(await _current(store)) == (0 if forget_positive else 1)
    assert not (await reproject_claim_route(store.l2.db_path, claim_id=negative["claim_id"])).claim_active
    if not forget_positive:
        assert (await _current(store))[0]["valid_to"] is None


@pytest.mark.asyncio
async def test_denial_and_forgetting_cannot_override_explicit_correction(relationship_memory):
    store, adapter = relationship_memory
    first = time.time() - 300
    await _say_relation(store, adapter, "first", at=first)
    row = (await _current(store))[0]
    correction = await store.l2.apply_relationship_correction(
        triple_id=row["triple_id"], request_id="reject-residence", actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
    )
    assert correction is not None
    await _say_relation(store, adapter, "withdrawal", at=first + 100, negative=True)
    await store.forget_source_events(["withdrawal"])
    await _say_relation(store, adapter, "again", at=first + 200)
    assert not await _current(store)


@pytest.mark.asyncio
async def test_late_denial_does_not_remove_newer_positive(relationship_memory):
    store, adapter = relationship_memory
    first = time.time() - 300
    await _say_relation(store, adapter, "first", at=first)
    await _say_relation(store, adapter, "newer", at=first + 200)
    await _say_relation(store, adapter, "late-denial", at=first + 100, negative=True)
    assert len(await _current(store)) == 1
    assert (await _current(store))[0]["valid_to"] is None


@pytest.mark.asyncio
async def test_denial_arriving_before_older_support_still_closes_it(relationship_memory):
    store, adapter = relationship_memory
    first = time.time() - 300
    await _say_relation(store, adapter, "withdrawal", at=first + 100, negative=True)
    await _say_relation(store, adapter, "late-first", at=first)
    assert not await _current(store)
    assert (await _current(store, at=first + 1))[0]["valid_to"] == first + 100


@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [
    {"cue": "one_off"},
    {"raw": "下周", "cue": "recent"},
    {"evidence_mode": "clarification"},
    {"assertion_mode": "hypothetical"},
    {"assertion_mode": "quoted"},
    {"assertion_mode": "conditional"},
])
async def test_untrusted_or_noncurrent_denial_keeps_relationship(relationship_memory, fields):
    store, adapter = relationship_memory
    first = time.time() - 300
    await _say_relation(store, adapter, "first", at=first)
    await _say_relation(store, adapter, "unsupported", at=first + 100, negative=True, **fields)
    assert len(await _current(store)) == 1
    assert (await _current(store))[0]["valid_to"] is None


@pytest.mark.asyncio
async def test_same_occurrence_contradiction_never_creates_positive_relationship(relationship_memory):
    store, adapter = relationship_memory
    await _say_relation(store, adapter, "conflicting", at=time.time() - 100, contradictory=True)
    assert not await _current(store)
    routes = await _read(store, "SELECT reason_code FROM l2_claim_projection_outcomes WHERE target_kind = 'route'")
    assert any(row["reason_code"] == "same_occurrence_relationship_conflict" for row in routes)


@pytest.mark.parametrize("predicate,object_type", [
    ("VISITED", "place"), ("USED", "software"), ("ATTENDED", "event"),
    ("INTERACTED_WITH", "person"), ("LOCATED_IN", "place"),
])
def test_historical_or_topological_denials_do_not_close_current_state(predicate, object_type):
    route = derive_semantic_route(_route_input(
        predicate, object_type=object_type, object_entity_id=TARGET_ID,
        subject_type="user", subject_id="user:u1",
        polarity="negative", fact_kind="explicit_fact",
    ))
    assert ProjectionTarget.EXCLUSION not in route.projection_targets
