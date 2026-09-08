"""Persisted Claim references must remain distinct from factual display names."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.events.events import EventLevel, EventTypes
from magi.core.sqlite import sqlite_connection_async
from magi.i18n import language_context
from magi.memory.l2.assertion_display import decorate_assertion_display
from magi.memory.l2.claim_text import load_claim_texts, persisted_claim_to_phase1
from magi.memory.l2.claims.identity import derive_claim_identity_key
from magi.memory.l2.claims.models import ClaimEntityRefInput
from magi.memory.l2.claims.reprojection_write import reproject_claim_route
from magi.memory.l2.factual_rendering import render_grounded_fact
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.entities.maintenance import L2EntityMaintenance
from magi.memory.l2.models import L2Phase1Result, derive_projection_attempt_key
from magi.memory.l2.llm_service import L2LLMService
from magi.memory.l2.pipeline import L2Pipeline
from magi.memory.l2.store import L2CognitionStore
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from magi.user_profile.portrait_projection_repository import UserPortraitProjectionRepository

from .test_phase1_entity_grounding import _entity
from .test_pipeline import UnifiedMemoryStore, _FakeAdapter, _FakeScenarioPool
from .test_grounded_claim_ledger import _claim_input, _evidence, _running_leases
from .test_claim_route_reprojection import _seed_claim

APPLE_ID = "other:source:7b25f5fba4e85deabb059555a6852c16"
PERSON_ID = "person:source:55f85a7b45634892a8fdd69d42b261ca"


@pytest.fixture(autouse=True)
def _chinese_language():
    with language_context("zh-CN"):
        yield


def _response(
    *,
    event_id: str,
    object_ref: str,
    evidence: str,
    entities: list[dict[str, object]],
    predicate: str = "LIKES",
    object_type: str = "other",
    fact_kind: str = "stable_preference",
    temporal_cue: str = "unspecified",
    raw_time_expression: str = "",
    subject_ref: str = "user:self",
    subject_type: str = "user",
    polarity: str = "positive",
    evidence_mode: str = "direct",
    antecedent_event_ids: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "entities": entities,
            "fact_claims": [{
                "assertion_mode": "asserted",
                "subject_ref": subject_ref,
                "subject_type": subject_type,
                "predicate": predicate,
                "object_ref": object_ref,
                "object_type": object_type,
                "fact_kind": fact_kind,
                "temporal_cue": temporal_cue,
                "raw_time_expression": raw_time_expression,
                "polarity": polarity,
                "specificity": "concrete",
                "evidence_text": evidence,
                "evidence_mode": evidence_mode,
                "antecedent_event_ids": antecedent_event_ids or [],
                "confidence": 0.9,
                "supporting_event_ids": [event_id],
            }],
            "resolved_refs": [],
            "diagnostics": {"entity_status": "found" if entities else "none"},
        },
        ensure_ascii=False,
    )


async def _open_store(base: Path, response: str) -> tuple[UnifiedMemoryStore, _FakeAdapter]:
    adapter = _FakeAdapter(response)
    store = UnifiedMemoryStore(
        l1_db_path=str(base / "l1_events.db"),
        memory_db_path=str(base / "memory.db"),
        persist_dir=str(base / "memories"),
        l2_batch_flush_interval_seconds=0,
        scenario_llm_pool=_FakeScenarioPool(adapter),
    )
    await store.initialize()
    return store, adapter


async def _ingest(store: UnifiedMemoryStore, *, event_id: str, content: str) -> None:
    result = await store.ingest_event({
        "id": event_id,
        "type": EventTypes.USER_MESSAGE,
        "timestamp": time.time(),
        "source": "chat",
        "level": EventLevel.INFO.value,
        "data": {"user_id": "u1", "session_id": f"session-{event_id}", "content": content},
    })
    assert result["l2_job_enqueued"] is True
    for _ in range(600):
        stats = store.get_l2_pipeline_stats()
        if stats["extract_completed"] >= 1 or stats["extract_failed"] >= 1:
            break
        await asyncio.sleep(0.01)
    stats = store.get_l2_pipeline_stats()
    assert stats["extract_failed"] == 0, stats
    assert stats["extract_completed"] == 1, stats


@pytest.mark.asyncio
@pytest.mark.parametrize("reference_form", ["existing_id", "existing_name", "alias", "new"])
async def test_entity_claim_name_survives_pipeline_restart_and_portrait(
    tmp_path: Path, reference_form: str,
) -> None:
    event_id = f"evt-apple-{reference_form}"
    surface = "苹果公司" if reference_form == "alias" else "苹果"
    existing = reference_form != "new"
    raw_ref = APPLE_ID if reference_form in {"existing_id", "alias"} else surface
    evidence = f"我蛮喜欢{surface}的"
    content = f"{evidence}，你觉得苹果产品怎么样"
    response = _response(
        event_id=event_id, object_ref=raw_ref, evidence=evidence,
        entities=[_entity(surface, surface, "other", resolved_id=APPLE_ID if existing else None)],
    )
    store, adapter = await _open_store(tmp_path, response)
    try:
        assert store.l2 is not None and store.l2_entity_catalog is not None
        if existing:
            await store.l2_entity_catalog.upsert_entity(
                entity_id=APPLE_ID, canonical_name="苹果", entity_type="other",
            )
        if reference_form == "alias":
            await store.l2_entity_catalog.add_alias(
                entity_id=APPLE_ID, alias_text=surface, confidence=0.98,
            )
        await _ingest(store, event_id=event_id, content=content)
        claims = await store.l2.list_grounded_claims()
        assert len(claims) == 1
        claim = claims[0]
        assert claim["object_value"] == raw_ref
        assert claim["object_surface"] == surface
        assert claim["subject_ref"] == "user:u1"
        assert claim["temporal_cue"] == "unspecified"
        assert claim["extractor_contract_version"] == 8
        hydrated_claim = await store.l2.get_grounded_claim(claim["claim_id"])
        assert hydrated_claim is not None
        evidence_rows = hydrated_claim["evidence"]
        assert len(evidence_rows) == 1
        evidence_row = evidence_rows[0]
        assert evidence_row["event_id"] == event_id
        assert evidence_row["author_type"] == "user"
        assert evidence_row["evidence_class"] == "user_self_report"
        locator = evidence_row["evidence_locator"]
        assert content[locator["start"]:locator["end"]] == evidence
        assert locator["quote_hash"] == hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        refs = await store.l2.list_claim_entity_refs(claim_id=claim["claim_id"])
        object_refs = [ref for ref in refs if ref["ref_role"] == "object"]
        assert len(object_refs) == 1
        target_id = object_refs[0]["entity_id"]
        if existing:
            assert target_id == APPLE_ID
        assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
        assert len(assertions) == 1
        assertion = assertions[0]
        assert assertion["natural_summary"] == "用户喜欢苹果。"
        assert assertion["target_entity_id"] == target_id
        assert assertion["trait_value"] == "like"
        assert assertion["temporal_scope"] == "stable"
        assert assertion["inference_depth"] == "direct"
        assert len(adapter.calls) == 1
    finally:
        await store.shutdown()

    restarted = L2CognitionStore(db_path=str(tmp_path / "memory.db"))
    await restarted.initialize()
    reloaded_claims = await restarted.list_grounded_claims()
    assert reloaded_claims == claims
    assertions = await restarted.list_current_assertions(entity_id="user:u1")
    decorated = await decorate_assertion_display(restarted.db_path, assertions)
    assert decorated[0]["display_text"] == "用户喜欢苹果。"
    assert decorated[0]["display_status"] == "complete"
    before_confirmation = await UserPortraitProjectionBuilder(restarted).build("u1")
    assert not before_confirmation.prompt_summary
    confirmed = await restarted.apply_user_feedback(
        assertion_id=assertions[0]["assertion_id"], feedback="confirmed",
    )
    assert confirmed is not None
    projection = await UserPortraitProjectionBuilder(restarted).build("u1")
    serialized = json.dumps(
        {"world": projection.world, "recent": projection.recent, "prompt": projection.prompt_summary},
        ensure_ascii=False,
    )
    assert "用户喜欢苹果。" in serialized
    assert "最近喜欢" not in serialized
    assert target_id not in serialized
    repository = UserPortraitProjectionRepository(restarted.db_path)
    await repository.upsert(projection)
    reloaded_projection = await UserPortraitProjectionRepository(restarted.db_path).get("u1")
    assert reloaded_projection is not None
    assert reloaded_projection.recent == projection.recent
    assert reloaded_projection.prompt_summary == projection.prompt_summary


@pytest.mark.asyncio
@pytest.mark.parametrize(("predicate", "object_type", "fact_kind", "literal", "evidence", "summary"), [
    ("PREFERRED_FORM_OF_ADDRESS", "other", "explicit_fact", "user:self", "请叫我user:self", "用户希望被称为user:self。"),
    ("BIRTH_DATE", "date", "explicit_fact", "1992-09-08", "我的生日是1992-09-08", "用户生日是1992-09-08。"),
    ("PLANS_TO", "activity", "future_intent", "去海边", "我计划去海边", "用户计划去海边。"),
])
async def test_literal_claim_values_are_not_entity_references(
    tmp_path: Path, predicate: str, object_type: str, fact_kind: str,
    literal: str, evidence: str, summary: str,
) -> None:
    event_id = f"evt-literal-{predicate}"
    store, adapter = await _open_store(tmp_path, _response(
        event_id=event_id, object_ref=literal, evidence=evidence, entities=[],
        predicate=predicate, object_type=object_type, fact_kind=fact_kind,
    ))
    try:
        assert store.l2_entity_catalog is not None
        await store.l2_entity_catalog.upsert_entity(
            entity_id=literal, canonical_name="另一个目录对象", entity_type="other",
        )
        await _ingest(store, event_id=event_id, content=evidence)
        assert store.l2 is not None
        claims = await store.l2.list_grounded_claims()
        assert len(claims) == 1
        claim = claims[0]
        assert claim["object_surface"] == literal
        assert claim["object_value"] == literal
        refs = await store.l2.list_claim_entity_refs(claim_id=claim["claim_id"])
        assert not [ref for ref in refs if ref["ref_role"] == "object"]
        assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
        assert len(assertions) == 1
        assert assertions[0]["natural_summary"] == summary
        decorated = await decorate_assertion_display(store.l2.db_path, assertions)
        assert decorated[0]["display_text"] == summary
        assert decorated[0]["display_status"] == "complete"
        assert len(adapter.calls) == 1
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_dislike_retains_explicit_recent_wording_and_source(tmp_path: Path) -> None:
    event_id = "evt-dislike-apple"
    evidence = "我最近不喜欢苹果"
    store, adapter = await _open_store(tmp_path, _response(
        event_id=event_id, object_ref=APPLE_ID, evidence=evidence,
        entities=[_entity("苹果", "苹果", "other", resolved_id=APPLE_ID)],
        predicate="DISLIKES", temporal_cue="recent", raw_time_expression="最近",
    ))
    try:
        assert store.l2 is not None and store.l2_entity_catalog is not None
        await store.l2_entity_catalog.upsert_entity(
            entity_id=APPLE_ID, canonical_name="苹果", entity_type="other",
        )
        await _ingest(store, event_id=event_id, content=evidence)
        claims = await store.l2.list_grounded_claims()
        assert claims[0]["polarity"] == "positive"
        assert claims[0]["canonical_predicate"] == "DISLIKES"
        assert claims[0]["raw_time_frame"]["raw"] == "最近"
        assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
        assert len(assertions) == 1
        assert assertions[0]["trait_value"] == "dislike"
        assert assertions[0]["natural_summary"] == "用户最近不喜欢苹果。 原文时间: 最近"
        projection = await UserPortraitProjectionBuilder(store.l2).build("u1")
        assert "最近不喜欢苹果" in "\n".join(projection.prompt_summary)
        assert APPLE_ID not in "\n".join(projection.prompt_summary)
        assert len(adapter.calls) == 1
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(("subject_id", "subject_type"), [(PERSON_ID, "person"), ("user:u2", "user")])
async def test_other_person_claim_does_not_become_self_profile(
    tmp_path: Path, subject_id: str, subject_type: str,
) -> None:
    event_id = "evt-other-person-apple"
    store, adapter = await _open_store(tmp_path, _response(
        event_id=event_id, object_ref=APPLE_ID, evidence="小李喜欢苹果",
        entities=[_entity("苹果", "苹果", "other", resolved_id=APPLE_ID)] + (
            [_entity("小李", "小李", "person", resolved_id=subject_id)]
            if subject_type == "person" else []
        ),
        subject_ref=subject_id, subject_type=subject_type,
    ))
    try:
        assert store.l2 is not None and store.l2_entity_catalog is not None
        catalog_entries = [(APPLE_ID, "苹果", "other")]
        if subject_type == "person":
            catalog_entries.append((subject_id, "小李", "person"))
        for entity_id, name, entity_type in catalog_entries:
            await store.l2_entity_catalog.upsert_entity(
                entity_id=entity_id, canonical_name=name, entity_type=entity_type,
            )
        await _ingest(store, event_id=event_id, content="小李喜欢苹果")
        claims = await store.l2.list_grounded_claims()
        assert len(claims) == 1
        assert claims[0]["subject_ref"] == subject_id
        assert claims[0]["subject_type"] == subject_type
        assert claims[0]["object_surface"] == "苹果"
        async with sqlite_connection_async(store.l2.db_path) as db:
            texts = await load_claim_texts(db, [claims[0]["claim_id"]])
        text = texts[claims[0]["claim_id"]]
        assert text.subject_name == ("小李" if subject_type == "person" else None)
        assert text.subject_is_self is False
        assert render_grounded_fact(
            persisted_claim_to_phase1(claims[0]), resolved_text=text,
        ) == ("小李喜欢苹果。" if subject_type == "person" else "")
        assert await store.l2.list_tom_assertions(entity_id="user:u1") == []
        projection = await UserPortraitProjectionBuilder(store.l2).build("u1")
        assert not projection.prompt_summary
        assert len(adapter.calls) == 1
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_unresolved_grounded_name_remains_evidence_without_fabricated_entity(tmp_path: Path) -> None:
    event_id = "evt-unresolved-name"
    store, adapter = await _open_store(tmp_path, _response(
        event_id=event_id, object_ref="那家小店", evidence="我喜欢那家小店", entities=[],
    ))
    try:
        await _ingest(store, event_id=event_id, content="我喜欢那家小店")
        assert store.l2 is not None
        claims = await store.l2.list_grounded_claims()
        assert len(claims) == 1
        claim = claims[0]
        assert claim["object_value"] == "那家小店"
        assert claim["object_surface"] == "那家小店"
        refs = await store.l2.list_claim_entity_refs(claim_id=claim["claim_id"])
        assert not [ref for ref in refs if ref["ref_role"] == "object"]
        async with sqlite_connection_async(store.l2.db_path) as db:
            texts = await load_claim_texts(db, [claim["claim_id"]])
        assert texts[claim["claim_id"]].object_entity_id is None
        assert texts[claim["claim_id"]].object_name == "那家小店"
        assert render_grounded_fact(
            persisted_claim_to_phase1(claim), resolved_text=texts[claim["claim_id"]],
        ) == "用户喜欢那家小店。"
        assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
        assert len(assertions) == 1
        assert assertions[0]["natural_summary"] == "用户喜欢那家小店。"
        assert not assertions[0]["target_entity_id"]
        assert len(adapter.calls) == 1
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_negative_polarity_claim_keeps_evidence_without_positive_summary(tmp_path: Path) -> None:
    event_id = "evt-negative-apple"
    store, adapter = await _open_store(tmp_path, _response(
        event_id=event_id, object_ref=APPLE_ID, evidence="我不喜欢苹果",
        entities=[_entity("苹果", "苹果", "other", resolved_id=APPLE_ID)],
        polarity="negative",
    ))
    try:
        assert store.l2 is not None and store.l2_entity_catalog is not None
        await store.l2_entity_catalog.upsert_entity(
            entity_id=APPLE_ID, canonical_name="苹果", entity_type="other",
        )
        await _ingest(store, event_id=event_id, content="我不喜欢苹果")
        claims = await store.l2.list_grounded_claims()
        assert len(claims) == 1
        claim = claims[0]
        assert claim["polarity"] == "negative"
        assert claim["object_surface"] == "苹果"
        async with sqlite_connection_async(store.l2.db_path) as db:
            texts = await load_claim_texts(db, [claim["claim_id"]])
        assert render_grounded_fact(
            persisted_claim_to_phase1(claim), resolved_text=texts[claim["claim_id"]],
        ) == ""
        assert await store.l2.list_tom_assertions(entity_id="user:u1") == []
        assert not (await UserPortraitProjectionBuilder(store.l2).build("u1")).prompt_summary
        assert len(adapter.calls) == 1
    finally:
        await store.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(("surface", "subject_ref", "subject_type", "expected"), [
    ("苹果", "user:u1", "user", "用户喜欢苹果。"),
    (None, "user:u1", "user", ""),
    ("opaque-reference", "user:u1", "user", ""),
    ("missing-reference", "user:u1", "user", ""),
    ("苹果", "unknown-subject", "person", ""),
    ("苹果", "user:u2", "user", ""),
])
async def test_reloaded_claim_requires_grounded_names_for_unresolved_endpoints(
    l2_store_with_schema, surface: str | None, subject_ref: str, subject_type: str, expected: str,
) -> None:
    store = l2_store_with_schema
    event_id = "evt-endpoint-name"
    leases = await _running_leases(store, [event_id])
    catalog = L2EntityCatalog(db_path=store.db_path)
    await catalog.initialize()
    await catalog.upsert_entity(
        entity_id="opaque-reference", canonical_name="苹果", entity_type="other",
    )
    identity_key = derive_claim_identity_key(
        extractor_contract_version=1, evidence_rule_version=1, user_id="u1",
        subject_ref=subject_ref, subject_type=subject_type,
        canonical_predicate="LIKES", fact_kind="explicit_fact", object_type="topic",
        polarity="positive", specificity="concrete", temporal_cue="unspecified",
        fact_valid_from=None, fact_valid_to=None, target_from=None, target_to=None,
        raw_time_frame=None, evidence_mode="direct", object_surface=surface,
        object_value="opaque-reference", supporting_event_ids=[event_id], antecedent_event_ids=[],
    )
    stored = await store.upsert_grounded_claim(
        claim=replace(
            _claim_input(identity_key=identity_key, projection_leases=leases),
            user_id="u1", subject_ref=subject_ref, subject_type=subject_type,
            object_value="opaque-reference", object_surface=surface,
            temporal_cue="unspecified",
        ),
        evidence=[replace(
            _evidence(event_id),
            evidence_locator=(
                {"reference_surfaces": {"object": surface}}
                if surface == "苹果" else {}
            ),
        )],
        projection_leases=leases,
    )
    restarted = L2CognitionStore(db_path=store.db_path)
    claim = await restarted.get_grounded_claim(stored["claim_id"])
    assert claim is not None
    async with sqlite_connection_async(store.db_path) as db:
        texts = await load_claim_texts(db, [claim["claim_id"]])
    rendered = render_grounded_fact(
        persisted_claim_to_phase1(claim), resolved_text=texts[claim["claim_id"]],
    )
    assert rendered == expected
    assert "opaque-reference" not in rendered
    assert "unknown-subject" not in rendered
    assert claim["object_surface"] == surface


@pytest.mark.asyncio
async def test_current_subject_reference_never_borrows_retired_subject_name(l2_store_with_schema) -> None:
    store = l2_store_with_schema
    leases = await _running_leases(store, ["evt-rebound-subject"])
    catalog = L2EntityCatalog(db_path=store.db_path)
    await catalog.initialize()
    for entity_id, name in [("person:old", "小李"), ("person:new", "person:new")]:
        await catalog.upsert_entity(entity_id=entity_id, canonical_name=name, entity_type="person")
    identity_key = derive_claim_identity_key(
        extractor_contract_version=1, evidence_rule_version=1, user_id="u1",
        subject_ref="person:old", subject_type="person", canonical_predicate="LIKES",
        fact_kind="explicit_fact", object_type="topic", polarity="positive",
        specificity="concrete", temporal_cue="unspecified", fact_valid_from=None,
        fact_valid_to=None, target_from=None, target_to=None, raw_time_frame=None,
        evidence_mode="direct", object_surface="苹果", object_value="苹果",
        supporting_event_ids=["evt-rebound-subject"], antecedent_event_ids=[],
    )
    stored = await store.upsert_grounded_claim(
        claim=replace(
            _claim_input(identity_key=identity_key, projection_leases=leases),
            user_id="u1", subject_ref="person:old", subject_type="person",
            object_value="苹果", object_surface="苹果", temporal_cue="unspecified",
        ),
        evidence=[replace(
            _evidence("evt-rebound-subject"),
            evidence_locator={"reference_surfaces": {"object": "苹果"}},
        )],
        projection_leases=leases,
    )
    for version, entity_id in [(1, "person:old"), (2, "person:new")]:
        await store.upsert_claim_entity_ref(
            ClaimEntityRefInput(
                claim_id=stored["claim_id"], ref_role="subject",
                entity_id=entity_id, resolution_version=version,
            ),
            projection_leases=leases,
        )
    async with sqlite_connection_async(store.db_path) as db:
        texts = await load_claim_texts(db, [stored["claim_id"]])
    resolved = texts[stored["claim_id"]]
    assert resolved.subject_entity_id == "person:new"
    assert resolved.subject_name is None
    assert render_grounded_fact(persisted_claim_to_phase1(stored), resolved_text=resolved) == ""


@pytest.mark.asyncio
async def test_route_replay_never_converts_retired_identity_to_text_target(l2_store_with_schema) -> None:
    store = l2_store_with_schema
    retired_id = "topic:retired-reference"
    catalog = L2EntityCatalog(db_path=store.db_path)
    await catalog.initialize()
    await catalog.upsert_entity(entity_id=retired_id, canonical_name="苹果", entity_type="topic")
    await _seed_claim(
        store, claim_id="clm-retired-object", predicate="LIKES", created_at=time.time(),
        object_entity_id=retired_id, user_id="u1", subject_ref="user:u1", subject_type="user",
        fact_kind="stable_preference", object_type="topic", object_value=retired_id,
        temporal_cue="unspecified",
    )
    before = await reproject_claim_route(store.db_path, claim_id="clm-retired-object")
    assert before.decision is not None
    assert before.decision.target_entity_id == retired_id
    assert not before.decision.object_surface
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            "UPDATE l2_claim_entity_refs SET invalidated_at = ?, invalidated_reason = 'entity_merged' "
            "WHERE claim_id = ? AND ref_role = 'object'",
            (time.time(), "clm-retired-object"),
        )
        await db.commit()
    replayed = await reproject_claim_route(store.db_path, claim_id="clm-retired-object")
    assert replayed.decision is not None
    assert replayed.decision.disposition.value == "unrouted"
    assert replayed.decision.reason_code == "invalid_target_text"
    assert replayed.decision.target_entity_id is None
    assert not replayed.decision.object_surface
    assert not replayed.decision.can_project_assertion
    retained = await store.get_grounded_claim("clm-retired-object")
    assert retained is not None
    assert retained["object_surface"] == retired_id


@pytest.mark.asyncio
async def test_pipeline_retry_keeps_latest_merged_subject_and_object_refs(l2_store_with_schema, monkeypatch) -> None:
    store = l2_store_with_schema
    claim_id = "clm-merge-retry"
    event_id = "evt-merge-retry"
    leases = await _running_leases(store, [event_id])
    catalog = L2EntityCatalog(db_path=store.db_path)
    for entity_id, name, entity_type in [
        ("person:old", "小李", "person"), ("person:merged", "小李", "person"),
        ("topic:old", "苹果", "topic"), ("topic:merged", "苹果", "topic"),
    ]:
        await catalog.upsert_entity(entity_id=entity_id, canonical_name=name, entity_type=entity_type)
    await _seed_claim(
        store, claim_id=claim_id, predicate="LIKES", created_at=time.time(),
        object_entity_id="topic:old", user_id="u1", subject_ref="person:old", subject_type="person",
        fact_kind="stable_preference", object_type="topic", object_value="topic:old",
        temporal_cue="unspecified", evidence_event_id=event_id,
    )
    await store.upsert_claim_entity_ref(
        ClaimEntityRefInput(claim_id=claim_id, ref_role="subject", entity_id="person:old", resolution_version=1),
        projection_leases=leases,
    )
    maintenance = L2EntityMaintenance(db_path=store.db_path)
    await maintenance._merge_entity_into("person:merged", "person:old")
    await maintenance._merge_entity_into("topic:merged", "topic:old")
    refs_before = await store.list_claim_entity_refs(claim_id=claim_id)
    assert {(item["ref_role"], item["entity_id"], item["resolution_version"]) for item in refs_before} == {
        ("subject", "person:merged", 2), ("object", "topic:merged", 2),
    }
    claim = await store.get_grounded_claim(claim_id)
    assert claim is not None
    phase1 = L2Phase1Result(fact_claims=[persisted_claim_to_phase1(claim)])
    pipeline = L2Pipeline(store, entity_catalog=catalog, llm_service=L2LLMService(None))

    def unexpected_resolution(**_kwargs):
        raise AssertionError("A current governed entity reference must not be resolved again")

    monkeypatch.setattr(pipeline, "_resolve_grounded_object_id", unexpected_resolution)
    batch = SimpleNamespace(
        projection_leases=leases, self_entity_id="user:u1", catalog_name_index={},
        attempt_key=derive_projection_attempt_key(leases),
    )
    object_refs = await pipeline._persist_grounded_claim_entity_refs(batch, phase1, [])
    assert object_refs == {claim_id: ("topic:merged", "topic")}
    assert phase1.fact_claims[0].subject_ref == "person:merged"
    routes = await pipeline._route_grounded_phase1_claims(batch, phase1, object_refs=object_refs)
    assert routes[claim_id].subject_id == "person:merged"
    assert routes[claim_id].target_entity_id == "topic:merged"
    outcomes = await store.list_claim_projection_outcomes(claim_id=claim_id)
    route_receipts = [item for item in outcomes if item["target_kind"] == "route"]
    assert len(route_receipts) == 1
    assert route_receipts[0]["details"]["subject_resolution_version"] == 2
    assert route_receipts[0]["details"]["object_resolution_version"] == 2
    assert await store.list_claim_entity_refs(claim_id=claim_id) == refs_before
    async with sqlite_connection_async(store.db_path) as db:
        texts = await load_claim_texts(db, [claim_id])
    assert render_grounded_fact(phase1.fact_claims[0], resolved_text=texts[claim_id]) == "小李喜欢苹果。"
    retained = await store.get_grounded_claim(claim_id)
    assert retained is not None
    assert retained["subject_ref"] == "person:old"
    assert retained["object_value"] == "topic:old"


@pytest.mark.asyncio
async def test_catalog_rename_changes_display_without_changing_route_receipt(l2_store_with_schema) -> None:
    store = l2_store_with_schema
    claim_id = "clm-catalog-rename"
    entity_id = "topic:apple"
    catalog = L2EntityCatalog(db_path=store.db_path)
    await catalog.upsert_entity(entity_id=entity_id, canonical_name="苹果公司", entity_type="topic")
    await _seed_claim(
        store, claim_id=claim_id, predicate="LIKES", created_at=time.time(),
        object_entity_id=entity_id, user_id="u1", subject_ref="user:u1", subject_type="user",
        fact_kind="stable_preference", object_type="topic", object_value="苹果",
        temporal_cue="unspecified", evidence_event_id="evt-catalog-rename",
    )
    before = await reproject_claim_route(store.db_path, claim_id=claim_id)
    assert before.decision is not None
    assert before.decision.object_surface == "苹果"
    before_receipts = await store.list_claim_projection_outcomes(claim_id=claim_id)
    await catalog.upsert_entity(
        entity_id=entity_id, canonical_name="苹果品牌", entity_type="topic", allow_rename=True,
    )
    replayed = await reproject_claim_route(store.db_path, claim_id=claim_id)
    assert replayed.decision == before.decision
    assert replayed.route_outcome_appended is False
    assert await store.list_claim_projection_outcomes(claim_id=claim_id) == before_receipts
    async with sqlite_connection_async(store.db_path) as db:
        texts = await load_claim_texts(db, [claim_id])
    text = texts[claim_id]
    assert text.object_surface == "苹果"
    assert text.object_name == "苹果品牌"
    claim = await store.get_grounded_claim(claim_id)
    assert claim is not None
    assert render_grounded_fact(persisted_claim_to_phase1(claim), resolved_text=text) == "用户喜欢苹果品牌。"


@pytest.mark.asyncio
async def test_contextual_confirmation_resolves_catalog_without_new_mention_evidence(tmp_path: Path) -> None:
    event_id = "evt-confirmation-apple"
    antecedent_id = "evt-assistant-apple"
    confirmation = "是的，我就是很喜欢它"
    store, adapter = await _open_store(tmp_path, _response(
        event_id=event_id, object_ref=APPLE_ID, evidence=confirmation,
        entities=[_entity("苹果", "苹果", "other", resolved_id=APPLE_ID)],
        evidence_mode="confirmation", antecedent_event_ids=[antecedent_id],
    ))
    try:
        assert store.l2 is not None and store.l2_entity_catalog is not None
        await store.l2_entity_catalog.upsert_entity(
            entity_id=APPLE_ID, canonical_name="苹果", entity_type="other",
        )
        await store.ingest_event({
            "id": antecedent_id, "type": EventTypes.AI_RESPONSE,
            "timestamp": time.time() - 1, "source": "assistant", "level": EventLevel.INFO.value,
            "data": {
                "user_id": "u1", "session_id": f"session-{event_id}",
                "content": "你喜欢苹果，对吗？",
            },
        })
        await _ingest(store, event_id=event_id, content=confirmation)
        claims = await store.l2.list_grounded_claims()
        assert len(claims) == 1
        claim = await store.l2.get_grounded_claim(claims[0]["claim_id"])
        assert claim is not None
        assert claim["object_value"] == APPLE_ID
        assert claim["object_surface"] != APPLE_ID
        assert claim["confidence"] <= 0.75
        assert {(item["event_id"], item["link_role"], item["author_type"]) for item in claim["evidence"]} == {
            (event_id, "supporting", "user"), (antecedent_id, "antecedent", "assistant"),
        }
        assertions = await store.l2.list_tom_assertions(entity_id="user:u1")
        assert len(assertions) == 1
        assert assertions[0]["natural_summary"] == "用户喜欢苹果。"
        assert assertions[0]["target_entity_id"] == APPLE_ID
        async with sqlite_connection_async(store.l2.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM entity_name_evidence WHERE event_id = ?", (event_id,),
            ) as cursor:
                assert (await cursor.fetchone())[0] == 0
        assert len(adapter.calls) == 1
    finally:
        await store.shutdown()
