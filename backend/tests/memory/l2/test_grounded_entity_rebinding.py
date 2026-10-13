"""Entity resolver decisions survive extraction references rejected by the catalog."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import time

import pytest

from magi.memory.l2.models import L2Phase1FactClaim, ResolvedEntityMention
from magi.memory.l2.pipeline.claim_persistence import _resolved_grounded_surface_id
from magi.memory.manual_entries.l1_projector import ManualEntryL1Projector
from magi.memory.manual_entries.models import ManualEntry

from .test_claim_text_pipeline import _entity, _open_store, _response
from .test_preference_exclusions import _read


TARGET_ID = "entity:bb923b30b01b4d94a9485a08945170ed"
EXTRACTED_REF = "bb923b30b01b4d94a9485a08945170ed"


def _claim() -> L2Phase1FactClaim:
    return L2Phase1FactClaim(
        predicate="LIVES_IN", object_ref=EXTRACTED_REF, object_type="place",
        object_surface="上海", evidence_text="我现在不住在上海了。",
        supporting_event_ids=["denial"],
    )


def _mention(**changes) -> ResolvedEntityMention:
    return replace(ResolvedEntityMention(
        mention_text="上海", normalized_surface="上海", entity_type="place",
        resolved_entity_id=TARGET_ID, confidence=1, evidence_event_ids=["denial"],
    ), **changes)


@pytest.mark.parametrize("mentions", [
    [],
    [_mention(resolved_entity_id=None)],
    [_mention(entity_type="organization")],
    [_mention(evidence_event_ids=["another-event"])],
    [_mention(mention_text="北京", normalized_surface="北京")],
    [_mention(), _mention(resolved_entity_id="entity:other-place")],
    [_mention(), _mention(resolved_entity_id=None)],
])
def test_surface_binding_rejects_ungrounded_or_ambiguous_identity(mentions):
    assert _resolved_grounded_surface_id(
        _claim(), object_type="place", resolved_mentions=mentions,
    ) is None


def test_surface_binding_requires_grounded_surface_and_keeps_immutable_reference():
    claim = _claim()
    assert _resolved_grounded_surface_id(
        claim, object_type="place", resolved_mentions=[_mention()],
    ) == TARGET_ID
    assert claim.object_ref == EXTRACTED_REF
    assert _resolved_grounded_surface_id(
        replace(claim, object_surface=None), object_type="place", resolved_mentions=[_mention()],
    ) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("resolution_decision,cue,raw,calendar_expression,closes_current", [
    ("match", "stable", "", None, True),
    ("match", "recent", "现在", {"kind": "at_observation"}, True),
    ("match", "one_off", "", None, False),
    ("unresolved", "recent", "现在", {"kind": "at_observation"}, False),
])
async def test_manual_denial_uses_resolved_source_identity(
    tmp_path, resolution_decision, cue, raw, calendar_expression, closes_current,
):
    """Replay the real two-call output through manual L1 and the durable L2 queue."""
    store, adapter = await _open_store(tmp_path, "{}")
    first = time.time() - 300
    projector = ManualEntryL1Projector(memory=store)
    try:
        await store.l2_entity_catalog.upsert_entity(
            entity_id=TARGET_ID, canonical_name="上海", entity_type="place",
        )
        event_ids = []
        for index, content in enumerate(["我住在上海。", "我现在不住在上海了。"]):
            entry = ManualEntry(
                entry_id=f"note-{index}", created_at=first + index * 100,
                event_at=first + index * 100, body=content,
            )
            event_id = projector.event_id_for(entry, predecessor_event_id=None)
            event_ids.append(event_id)
            raw_ref = EXTRACTED_REF if index else TARGET_ID
            adapter._responses = [_response(
                event_id=event_id, object_ref=raw_ref, object_type="place",
                fact_kind="explicit_fact", evidence=content,
                entities=[_entity("上海", "上海", "place", resolved_id=raw_ref)],
                predicate="LIVES_IN", polarity="negative" if index else "positive",
                temporal_cue=cue if index else "stable",
                raw_time_expression=raw if index else "",
                calendar_expression=calendar_expression if index else None,
            )]
            if index:
                adapter._responses.append(json.dumps({"resolution": {
                    "decision": resolution_decision, "matched_entity_id": TARGET_ID,
                    "matched_entity_name": "上海", "confidence": 1,
                    "reason_tags": ["exact_name_match", "type_compatible"],
                    "should_merge": resolution_decision == "match",
                }}))
            before = store.get_l2_pipeline_stats()["extract_completed"]
            assert await projector.project_current(entry, predecessor_event_id=None) == event_id
            assert await store.replay_l2_extraction(event_id)
            for _ in range(800):
                stats = store.get_l2_pipeline_stats()
                if stats["extract_completed"] > before or stats["extract_failed"]:
                    break
                await asyncio.sleep(0.01)
            assert stats["extract_failed"] == 0, stats
            assert stats["extract_completed"] == before + 1, stats
        assert len(adapter.calls) == 3
        negative = next(row for row in await store.l2.list_grounded_claims() if row["polarity"] == "negative")
        assert negative["object_value"] == EXTRACTED_REF
        assert negative["object_surface"] == "上海"
        refs = await store.l2.list_claim_entity_refs(claim_id=negative["claim_id"])
        object_ids = [row["entity_id"] for row in refs if row["ref_role"] == "object"]
        current = await store.l2.list_current_relationships(subject_id="user:local_user")
        if resolution_decision == "unresolved":
            assert object_ids == []
            assert len(current) == 1 and current[0]["valid_to"] is None
            return
        assert object_ids == [TARGET_ID]
        if not closes_current:
            assert len(current) == 1 and current[0]["valid_to"] is None
            return
        assert current == []
        historical = await store.l2.list_current_relationships(
            subject_id="user:local_user", effective_at=first + 1,
        )
        assert [(row["valid_to"], row["evidence_event_ids"]) for row in historical] == [
            (first + 100, [event_ids[0]]),
        ]
        outcomes = await _read(store, "SELECT * FROM l2_claim_projection_outcomes WHERE target_kind = 'exclusion'")
        assert len(outcomes) == 1 and outcomes[0]["reason_code"] == "explicit_relationship_negation"
    finally:
        await store.shutdown()
