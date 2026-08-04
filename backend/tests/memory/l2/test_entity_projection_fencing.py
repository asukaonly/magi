"""Exact projection-attempt fencing for entity side effects."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.hybrid_retrieval.entity_semantic_builder import EntityScopedSemanticBuilder
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.models import (
    L2Phase1Entity,
    L2Phase1Result,
    L2ProjectionLease,
    ResolvedEntityMention,
)
from magi.memory.l2.pipeline import L2Pipeline
from magi.memory.l2.projection.errors import ProjectionAttemptFencedError


async def _running_lease(store, event_id: str) -> L2ProjectionLease:  # type: ignore[no-untyped-def]
    await store.enqueue_projection_job(
        event_id=event_id,
        source="chat",
        event_type="UserMessage",
    )
    row = (await store.claim_projection_jobs(consumer_name="entity-fence", limit=1))[0]
    lease = L2ProjectionLease(
        event_id=str(row["event_id"]),
        lease_token=str(row["lease_token"]),
        attempt_count=int(row["attempt_count"]),
    )
    assert (
        await store.bind_projection_job_batch(
            [lease],
            consumer_name="entity-fence",
        )
        == 1
    )
    assert (
        await store.mark_projection_jobs_running(
            [lease],
            consumer_name="entity-fence",
        )
        == 1
    )
    return lease


def _stale(lease: L2ProjectionLease) -> L2ProjectionLease:
    return L2ProjectionLease(
        event_id=lease.event_id,
        lease_token=f"stale-{lease.lease_token}",
        attempt_count=lease.attempt_count,
    )


def _event(event_id: str, content: str, *, metadata: dict | None = None):  # type: ignore[no-untyped-def]
    event = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": content,
                "author_type": "user",
                "content_type": "text",
            },
            metadata=metadata or {},
            source="chat",
            level=EventLevel.INFO,
            correlation_id=f"corr-{event_id}",
            event_id=event_id,
        )
    )
    event.metadata_json = dict(metadata or {})
    return event


@pytest.mark.asyncio
async def test_catalog_entity_alias_and_mention_writes_require_exact_lease(
    l2_store_with_schema,
) -> None:
    catalog = L2EntityCatalog(db_path=l2_store_with_schema.db_path, vector_enabled=False)
    lease = await _running_lease(l2_store_with_schema, "evt-entity-fence")
    stale = _stale(lease)

    with pytest.raises(ProjectionAttemptFencedError):
        await catalog.upsert_entity(
            canonical_name="Stale Entity",
            entity_type="software",
            entity_id="software:stale",
            source_event_ids=[lease.event_id],
            projection_leases=[stale],
        )
    assert await catalog.find_by_canonical_name("Stale Entity") == []

    await catalog.upsert_entity(
        canonical_name="Live Entity",
        entity_type="software",
        entity_id="software:live",
    )
    with pytest.raises(ProjectionAttemptFencedError):
        await catalog.add_alias(
            entity_id="software:live",
            alias_text="stale alias",
            source_event_ids=[lease.event_id],
            projection_leases=[stale],
        )
    assert (await catalog.resolve_alias("stale alias"))["decision"] == "unresolved"

    with pytest.raises(ProjectionAttemptFencedError):
        await catalog.record_mention(
            mention_text="stale mention",
            normalized_surface="stale mention",
            entity_type="software",
            evidence_event_ids=[lease.event_id],
            evidence_text="stale mention",
            resolved_entity_id="software:live",
            confidence=0.9,
            projection_leases=[stale],
        )
    assert await catalog.list_mentions() == []

    await catalog.add_alias(
        entity_id="software:live",
        alias_text="live alias",
        source_event_ids=[lease.event_id],
        projection_leases=[lease],
    )
    mention_id = await catalog.record_mention(
        mention_text="live mention",
        normalized_surface="live mention",
        entity_type="software",
        evidence_event_ids=[lease.event_id],
        evidence_text="live mention",
        resolved_entity_id="software:live",
        confidence=0.9,
        projection_leases=[lease],
    )
    replayed_mention_id = await catalog.record_mention(
        mention_text="live mention",
        normalized_surface="live mention",
        entity_type="software",
        evidence_event_ids=[lease.event_id],
        evidence_text="live mention",
        resolved_entity_id="software:live",
        confidence=0.9,
        projection_leases=[lease],
    )
    assert mention_id > 0
    assert replayed_mention_id == mention_id
    assert len(await catalog.list_mentions()) == 1
    assert (await catalog.resolve_alias("live alias"))["entity_id"] == "software:live"

    regular_id = await catalog.upsert_entity(
        canonical_name="Regular Entity",
        entity_type="software",
        entity_id="software:regular",
    )
    assert regular_id == "software:regular"


@pytest.mark.asyncio
async def test_phase1_and_structured_entity_writes_receive_batch_lease(
    l2_store_with_schema,
) -> None:
    catalog = L2EntityCatalog(db_path=l2_store_with_schema.db_path, vector_enabled=False)
    lease = await _running_lease(l2_store_with_schema, "evt-entity-pipeline")
    stale = _stale(lease)
    pipeline = L2Pipeline.__new__(L2Pipeline)
    pipeline._entity_catalog = catalog
    pipeline._llm_service = None
    pipeline._entity_resolution_cache = {}

    event = _event(
        lease.event_id,
        "Magi is useful",
        metadata={
            "structured_entity_hints": [
                {
                    "mention_text": "Magi",
                    "canonical_name_hint": "Magi",
                    "entity_type": "software",
                    "resolved_entity_id": "software:magi",
                }
            ]
        },
    )
    with pytest.raises(ProjectionAttemptFencedError):
        await pipeline._upsert_structured_hint_entities(
            event,
            projection_leases=[stale],
        )
    assert await catalog.find_by_canonical_name("Magi") == []

    phase1 = L2Phase1Result(
        entities=[
            L2Phase1Entity(
                surface="Magi",
                normalized_name="Magi",
                entity_type="software",
                confidence=0.95,
            )
        ]
    )
    with pytest.raises(ProjectionAttemptFencedError):
        await pipeline._resolve_phase1_entities(
            event,
            phase1,
            evidence_event_ids=[lease.event_id],
            evidence_events=[event],
            projection_leases=[stale],
        )
    assert await catalog.find_by_canonical_name("Magi") == []
    assert await catalog.list_mentions() == []

    assert (
        await pipeline._upsert_structured_hint_entities(
            event,
            projection_leases=[lease],
        )
        == 1
    )
    assert (await catalog.resolve_alias("Magi"))["entity_id"] == "software:magi"


class _SemanticL1:
    async def get_entity_event_ids(self, _entity_ids, *, limit_per_entity):  # type: ignore[no-untyped-def]
        _ = limit_per_entity
        return {"topic:scope": ["evt-sibling"]}

    async def get_event_vectors(self, _event_ids):  # type: ignore[no-untyped-def]
        return {
            "evt-semantic-fence": [1.0, 0.0],
            "evt-sibling": [1.0, 0.0],
        }

    async def get_event_entity_ids(self, _event_ids):  # type: ignore[no-untyped-def]
        return {
            "evt-semantic-fence": ["topic:scope", "topic:new"],
            "evt-sibling": ["topic:scope", "topic:old"],
        }


@pytest.mark.asyncio
async def test_semantic_edge_write_is_exactly_fenced(l2_store_with_schema) -> None:
    lease = await _running_lease(l2_store_with_schema, "evt-semantic-fence")
    builder = EntityScopedSemanticBuilder(
        _SemanticL1(),
        l2_store_with_schema,
        similarity_threshold=0.5,
    )

    with pytest.raises(ProjectionAttemptFencedError):
        await builder.build_edges_for_event(
            lease.event_id,
            ["topic:scope", "topic:new"],
            observed_at=1.0,
            projection_leases=[_stale(lease)],
        )
    assert await l2_store_with_schema.get_relationships(subject_id="topic:new") == []

    assert (
        await builder.build_edges_for_event(
            lease.event_id,
            ["topic:scope", "topic:new"],
            observed_at=1.0,
            projection_leases=[lease],
        )
        == 1
    )


class _RecordingL1:
    def __init__(self) -> None:
        self.mappings: list[tuple] = []

    async def write_event_entities(self, mappings):  # type: ignore[no-untyped-def]
        self.mappings.extend(mappings)


class _FencedSemanticBuilder:
    async def build_edges_for_event(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise ProjectionAttemptFencedError("projection_attempt_fenced")


@pytest.mark.asyncio
async def test_pipeline_does_not_swallow_semantic_edge_fence() -> None:
    pipeline = L2Pipeline.__new__(L2Pipeline)
    pipeline._l1_store = None
    pipeline._semantic_edge_builder = _FencedSemanticBuilder()
    event = _event("evt-semantic-pipeline-fence", "Magi")

    with pytest.raises(ProjectionAttemptFencedError):
        await pipeline._build_entity_semantic_edges(
            event=event,
            resolved_mentions=[
                ResolvedEntityMention(
                    mention_text="Magi",
                    normalized_surface="Magi",
                    entity_type="software",
                    resolved_entity_id="software:magi",
                    confidence=0.95,
                    evidence_event_ids=[event.event_id],
                )
            ],
            projection_leases=[],
        )


@pytest.mark.asyncio
async def test_stale_preflight_blocks_cross_database_l1_entity_links(
    l2_store_with_schema,
) -> None:
    lease = await _running_lease(l2_store_with_schema, "evt-l1-link-fence")
    l1 = _RecordingL1()
    pipeline = L2Pipeline.__new__(L2Pipeline)
    pipeline._cognition_store = l2_store_with_schema
    pipeline._l1_store = l1
    pipeline._semantic_edge_builder = None
    event = _event(lease.event_id, "Magi")
    batch = SimpleNamespace(
        projection_leases=[_stale(lease)],
        stored_event=event,
        batch_event_ids=[lease.event_id],
    )
    phase1_flow = SimpleNamespace(
        resolved_mentions=[
            ResolvedEntityMention(
                mention_text="Magi",
                normalized_surface="Magi",
                entity_type="software",
                resolved_entity_id="software:magi",
                confidence=0.95,
                evidence_event_ids=[lease.event_id],
            )
        ]
    )

    with pytest.raises(RuntimeError, match="projection_attempt_fenced"):
        await pipeline._persist_phase1_outputs(batch, phase1_flow)
    assert l1.mappings == []
