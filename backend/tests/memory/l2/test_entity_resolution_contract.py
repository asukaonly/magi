"""Identity decisions must not follow names or stale type prefixes."""

from types import SimpleNamespace

import pytest

from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.models import L2Phase1Entity
from magi.memory.l2.pipeline import L2Pipeline
from magi.memory.l2.pipeline.entities.resolution import _PendingPhase1EntityResolution
from magi.memory.l2.storage.utils import normalize_store_entity_ref


@pytest.fixture
async def pipeline(tmp_path):
    item = L2Pipeline.__new__(L2Pipeline)
    item._entity_catalog = L2EntityCatalog(
        db_path=str(tmp_path / "memory.db"), vector_enabled=False
    )
    item._llm_service = None
    return item


@pytest.mark.asyncio
async def test_identity_is_opaque_and_current_type_is_catalog_owned(pipeline):
    catalog = pipeline._entity_catalog
    stored_id = await catalog.upsert_entity(
        entity_id="other:apple", canonical_name="Apple", entity_type="organization"
    )
    assert stored_id == "other:apple"
    assert normalize_store_entity_ref(stored_id, "organization") == stored_id
    assert await pipeline._entity_type_from_id(stored_id) == "organization"
    assert (
        await pipeline._prefer_existing_same_name_entity(
            proposed_entity_id="invented:id",
            canonical_name="Apple",
            entity_type="organization",
            mention_text="Apple",
            confidence=1,
            source_event_ids=[],
        )
        is None
    )


@pytest.mark.asyncio
async def test_candidate_recall_keeps_cross_type_homonyms(pipeline):
    catalog = pipeline._entity_catalog
    for kind in ("organization", "group", "brand"):
        await catalog.upsert_entity(
            entity_id=f"{kind}:apple", canonical_name="Apple", entity_type=kind
        )
    candidates = await catalog.find_resolution_candidates("Apple", entity_type="group")
    assert {row["entity_type"] for row in candidates} == {"organization", "group", "brand"}
    assert "apple" not in await pipeline._build_catalog_name_index()


@pytest.mark.asyncio
async def test_concrete_match_is_applied_but_uncertainty_does_not_create(pipeline):
    await pipeline._entity_catalog.upsert_entity(
        entity_id="organization:apple", canonical_name="Apple", entity_type="organization"
    )
    candidate = _PendingPhase1EntityResolution(
        entity=L2Phase1Entity(surface="Apple", entity_type="organization", confidence=0.95),
        mention_text="Apple",
        normalized_surface="Apple",
        entity_type="organization",
        mention_confidence=0.95,
        llm_mention_key="0",
        candidate_ids=("organization:apple",),
    )
    await pipeline._apply_phase1_llm_resolution(
        candidate,
        llm_results={
            "0": SimpleNamespace(
                decision="match", matched_entity_id="organization:apple", confidence=0.95
            )
        },
        projection_leases=(),
    )
    assert candidate.resolved_entity_id == "organization:apple"
    candidate.resolved_entity_id = None
    await pipeline._apply_phase1_llm_resolution(
        candidate, llm_results={"0": SimpleNamespace(decision="unresolved")}, projection_leases=()
    )
    assert candidate.resolved_entity_id is None
    assert len(await pipeline._entity_catalog.list_entities(limit=None)) == 1


@pytest.mark.asyncio
async def test_software_name_does_not_reuse_company(pipeline):
    await pipeline._entity_catalog.upsert_entity(
        entity_id="organization:apple", canonical_name="Apple", entity_type="organization"
    )
    resolved, _ = await pipeline._finalize_unresolved_entity(
        mention={"is_new": True},
        entity_type="software",
        mention_text="Apple",
        mention_confidence=0.95,
        source_event_ids=["event-new"],
    )
    assert resolved != "organization:apple"
    assert len(await pipeline._entity_catalog.list_entities(limit=None)) == 2


@pytest.mark.asyncio
async def test_episode_hints_use_current_type_and_deduplicate(pipeline):
    catalog = pipeline._entity_catalog
    await catalog.upsert_entity(
        entity_id="other:city", canonical_name="Shanghai", entity_type="place"
    )
    await catalog.upsert_entity(
        entity_id="place:old-topic", canonical_name="Architecture", entity_type="topic"
    )
    assert await pipeline._derive_place_and_topic_hints(
        ["other:city", "other:city", "place:old-topic"]
    ) == (["other:city"], ["place:old-topic"])
    assert await pipeline._derive_place_and_topic_hints([]) == ([], [])


@pytest.mark.asyncio
async def test_two_new_homonyms_in_one_event_never_share_an_allocated_id(pipeline):
    first, _ = await pipeline._finalize_unresolved_entity(
        mention={"is_new": True},
        entity_type="food",
        mention_text="Apple",
        mention_confidence=0.95,
        source_event_ids=["same-event"],
    )
    second, _ = await pipeline._finalize_unresolved_entity(
        mention={"is_new": True},
        entity_type="organization",
        mention_text="Apple",
        mention_confidence=0.95,
        source_event_ids=["same-event"],
    )
    third, _ = await pipeline._finalize_unresolved_entity(
        mention={"is_new": True},
        entity_type="organization",
        mention_text="Apple",
        mention_confidence=0.95,
        source_event_ids=["same-event"],
    )
    assert len({first, second, third}) == 3
    assert {row["entity_type"] for row in await pipeline._entity_catalog.list_entities()} == {
        "food",
        "organization",
    }


@pytest.mark.asyncio
async def test_same_type_homonyms_have_separate_local_resolution_cache_entries(
    pipeline, monkeypatch
):
    from magi.events.events import Event, EventTypes
    from magi.memory.event_contracts import normalize_runtime_event
    from magi.memory.l2.models import L2Phase1Result

    pipeline._entity_resolution_cache = {}
    for entity_id in ("organization:apple-tech", "organization:apple-records"):
        await pipeline._entity_catalog.upsert_entity(
            entity_id=entity_id, canonical_name="Apple", entity_type="organization"
        )
    batches = []

    async def resolve(*, items, **kwargs):
        batches.append([item.mention_key for item in items])
        return {
            str(i): SimpleNamespace(decision="match", matched_entity_id=entity_id, confidence=0.95)
            for i, entity_id in enumerate(("organization:apple-tech", "organization:apple-records"))
        }

    pipeline._llm_service = SimpleNamespace(resolve_entities_batch=resolve)
    event = normalize_runtime_event(
        Event(
            event_id="same-event",
            type=EventTypes.USER_MESSAGE,
            data={"content": "Apple and Apple", "author_type": "user"},
            source="chat",
        )
    )

    def fresh_result():
        return L2Phase1Result(
            entities=[
                L2Phase1Entity(surface="Apple", entity_type="organization", confidence=0.95)
                for _ in range(2)
            ]
        )

    first = await pipeline._resolve_phase1_entities(
        event, fresh_result(), evidence_event_ids=["same-event"]
    )
    second = await pipeline._resolve_phase1_entities(
        event, fresh_result(), evidence_event_ids=["same-event"]
    )
    assert [item.resolved_entity_id for item in first] == [
        "organization:apple-tech",
        "organization:apple-records",
    ]
    assert [item.resolved_entity_id for item in second] == [
        item.resolved_entity_id for item in first
    ]
    assert batches == [["0", "1"]]
