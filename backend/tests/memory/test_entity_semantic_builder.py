"""Entity-scoped semantic edges preserve scope, evidence, and bounded writes."""

from unittest.mock import AsyncMock
import pytest
from magi.config.models import AppConfig, MemorySettings
from magi.memory.hybrid_retrieval.entity_semantic_builder import (
    EntityScopedSemanticBuilder,
    cosine_similarity,
    _select_cross_entity_pairs,
    _type_from_id,
)


def _mock_l1_store(entity_events=None, event_entities=None, event_vectors=None):
    store = AsyncMock()

    async def get_entity_event_ids(entity_ids, *, limit_per_entity=20):
        mapping = entity_events or {}
        return {eid: mapping.get(eid, [])[:limit_per_entity] for eid in entity_ids}

    async def get_event_entity_ids(event_ids):
        mapping = event_entities or {}
        return {eid: mapping.get(eid, []) for eid in event_ids}

    async def get_event_vectors(event_ids):
        vectors = event_vectors or {}
        return {eid: vectors[eid] for eid in event_ids if eid in vectors}

    store.get_entity_event_ids = AsyncMock(side_effect=get_entity_event_ids)
    store.get_event_entity_ids = AsyncMock(side_effect=get_event_entity_ids)
    store.get_event_vectors = AsyncMock(side_effect=get_event_vectors)
    return store


def _mock_l2_store():
    store = AsyncMock()
    store.upsert_knowledge_edge = AsyncMock(return_value="triple_123")
    return store


@pytest.fixture
def eligible_stores():
    return (
        _mock_l1_store(
            entity_events={"person:alice": ["evt1", "evt2"]},
            event_entities={
                "evt1": ["person:alice", "concept:python"],
                "evt2": ["person:alice", "concept:java"],
            },
            event_vectors={"evt1": [2.0, 0.0], "evt2": [3.0, 4.0]},
        ),
        _mock_l2_store(),
    )


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], 1.0),
        ([1.0, 0.0], [0.0, 1.0], 0.0),
        ([1.0, 0.0], [-1.0, 0.0], -1.0),
        ([0.0, 0.0], [1.0, 2.0], 0.0),
        ([1.0, 2.0], [0.0, 0.0], 0.0),
        ([2.0, 0.0], [3.0, 4.0], 0.6),
    ],
)
def test_cosine_normalizes_magnitude_and_handles_zero_vectors(a, b, expected):
    assert cosine_similarity(a, b) == pytest.approx(expected)


class TestTypeFromId:
    @pytest.mark.parametrize(
        "expected_type,entity_id_input",
        [
            pytest.param("person", "person:abc123", id="prefixed_id"),
            pytest.param("entity", "unknown", id="unprefixed_id"),
            pytest.param("concept", "concept:ai:ml", id="multi_colon"),
        ],
    )
    def test_type_from_id_handles_prefix_forms(self, expected_type, entity_id_input):
        assert _type_from_id(entity_id_input) == expected_type


@pytest.mark.parametrize(
    "new_only,sib_only,shared,expected",
    [
        (
            {"person:alice"},
            {"place:tokyo"},
            {"concept:ai"},
            {("person:alice", "place:tokyo", "person", "place")},
        ),
        (
            {"person:alice"},
            set(),
            {"concept:ai"},
            {("person:alice", "concept:ai", "person", "concept")},
        ),
        (
            set(),
            {"place:tokyo"},
            {"concept:ai"},
            {("concept:ai", "place:tokyo", "concept", "place")},
        ),
        (set(), set(), {"concept:ai"}, set()),
        (
            {"person:alice", "software:python"},
            {"place:tokyo", "untyped"},
            {"concept:ai"},
            {
                ("person:alice", "place:tokyo", "person", "place"),
                ("person:alice", "untyped", "person", "entity"),
                ("software:python", "place:tokyo", "software", "place"),
                ("software:python", "untyped", "software", "entity"),
            },
        ),
    ],
)
def test_cross_entity_pair_direction_and_types(new_only, sib_only, shared, expected):
    pairs = _select_cross_entity_pairs(new_only, sib_only, shared)
    assert set(pairs) == expected
    assert len(pairs) == len(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("threshold,expected", [(0.59, 1), (0.6, 1), (0.61, 0)])
async def test_similarity_threshold_preserves_exact_edge_provenance(
    eligible_stores, threshold, expected
):
    l1, l2 = eligible_stores
    builder = EntityScopedSemanticBuilder(l1, l2, similarity_threshold=threshold)
    assert (
        await builder.build_edges_for_event("evt1", ["person:alice"], observed_at=1000.0)
        == expected
    )
    if not expected:
        l2.upsert_knowledge_edge.assert_not_awaited()
        return
    l2.upsert_knowledge_edge.assert_awaited_once_with(
        subject_id="concept:python",
        subject_type="concept",
        predicate="SEMANTIC_CONTEXT",
        object_id="concept:java",
        object_type="concept",
        fact_kind="semantic_edge",
        evidence_event_ids=["evt1", "evt2"],
        confidence=0.6,
        observed_at=1000.0,
        source_type="entity_semantic_builder",
        extraction_method="embedding_similarity",
        evidence_text="Cosine similarity 0.600 within shared entity scope",
        projection_leases=(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapped", [False, True], ids=["memory-settings", "app-config"])
@pytest.mark.parametrize("enabled", [None, False, True], ids=["default", "disabled", "enabled"])
async def test_real_config_enablement_controls_otherwise_eligible_edges(
    eligible_stores, wrapped, enabled
):
    l1, l2 = eligible_stores
    memory = MemorySettings()
    if enabled is not None:
        memory.entity_semantic_edges.enabled = enabled
    config = AppConfig(agent={"memory": memory}) if wrapped else memory
    builder = EntityScopedSemanticBuilder(
        l1, l2, config_getter=lambda: config, similarity_threshold=0.5
    )
    assert await builder.build_edges_for_event("evt1", ["person:alice"], observed_at=1000.0) == int(
        bool(enabled)
    )
    if enabled:
        l2.upsert_knowledge_edge.assert_awaited_once()
        assert l2.upsert_knowledge_edge.await_args.kwargs["object_id"] == "concept:java"
    else:
        assert l1.mock_calls == []
        l2.upsert_knowledge_edge.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["entities", "siblings", "new-vector", "sibling-vector"])
async def test_missing_prerequisite_stops_at_its_own_boundary(eligible_stores, missing):
    l1, l2 = eligible_stores
    entities = [] if missing == "entities" else ["person:alice"]
    if missing == "siblings":
        l1.get_entity_event_ids.side_effect = None
        l1.get_entity_event_ids.return_value = {"person:alice": ["evt1"]}
    if missing.endswith("vector"):
        l1.get_event_vectors.side_effect = None
        l1.get_event_vectors.return_value = (
            {"evt2": [3.0, 4.0]} if missing == "new-vector" else {"evt1": [2.0, 0.0]}
        )
    builder = EntityScopedSemanticBuilder(l1, l2, similarity_threshold=0.5)
    assert await builder.build_edges_for_event("evt1", entities, observed_at=1000.0) == 0
    l2.upsert_knowledge_edge.assert_not_awaited()
    l1.get_event_entity_ids.assert_not_awaited()
    if missing == "entities":
        l1.get_entity_event_ids.assert_not_awaited()
    else:
        l1.get_entity_event_ids.assert_awaited_once_with(["person:alice"], limit_per_entity=20)
    if missing in {"entities", "siblings"}:
        l1.get_event_vectors.assert_not_awaited()
    else:
        assert set(l1.get_event_vectors.await_args.args[0]) == {"evt1", "evt2"}


@pytest.mark.asyncio
async def test_scoped_siblings_preserve_exact_connections_and_continue_after_write_failure():
    l1 = _mock_l1_store(
        entity_events={
            "person:alice": ["evt1", "evt2", "bad-scope"],
            "concept:ai": ["evt1", "evt3"],
        },
        event_entities={
            "evt1": ["person:alice", "concept:ai"],
            "evt2": ["person:alice", "place:tokyo"],
            "evt3": ["concept:ai", "concept:robotics"],
            "bad-scope": ["person:bob", "place:paris"],
        },
        event_vectors={
            "evt1": [1.0, 0.0],
            "evt2": [1.0, 0.0],
            "evt3": [4.0, 3.0],
            "bad-scope": [1.0, 0.0],
        },
    )
    l2 = _mock_l2_store()
    builder = EntityScopedSemanticBuilder(l1, l2, similarity_threshold=0.5)
    expected = [
        ("concept:ai", "place:tokyo", ["evt1", "evt2"]),
        ("person:alice", "concept:robotics", ["evt1", "evt3"]),
    ]
    for fail_first in (False, True):
        l2.upsert_knowledge_edge.reset_mock()
        l2.upsert_knowledge_edge.side_effect = (
            [RuntimeError("database unavailable"), "triple_2"] if fail_first else None
        )
        assert await builder.build_edges_for_event(
            "evt1", ["person:alice", "concept:ai"], observed_at=1000.0
        ) == (1 if fail_first else 2)
        assert [
            (c.kwargs["subject_id"], c.kwargs["object_id"], c.kwargs["evidence_event_ids"])
            for c in l2.upsert_knowledge_edge.await_args_list
        ] == expected


class TestEntityScopedSemanticBuilder:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("cap", [0, 1, 3])
    async def test_edge_budget_counts_entity_pairs_across_siblings(self, cap):
        l1 = _mock_l1_store(
            entity_events={"person:alice": ["evt1", "high", "low"]},
            event_entities={
                "evt1": ["person:alice", "concept:new"],
                "high": ["person:alice", "concept:high_a", "concept:high_b"],
                "low": ["person:alice", "concept:low_a", "concept:low_b"],
            },
            event_vectors={"evt1": [1.0, 0.0], "high": [1.0, 0.0], "low": [4.0, 3.0]},
        )
        l2 = _mock_l2_store()
        builder = EntityScopedSemanticBuilder(
            l1_store=l1,
            l2_store=l2,
            similarity_threshold=0.5,
            max_edges_per_event=cap,
        )
        assert (
            await builder.build_edges_for_event("evt1", ["person:alice"], observed_at=1000.0) == cap
        )
        writes = [call.kwargs for call in l2.upsert_knowledge_edge.await_args_list]
        assert [
            (row["subject_id"], row["object_id"], row["evidence_event_ids"]) for row in writes
        ] == [
            ("concept:new", "concept:high_a", ["evt1", "high"]),
            ("concept:new", "concept:high_b", ["evt1", "high"]),
            ("concept:new", "concept:low_a", ["evt1", "low"]),
        ][
            :cap
        ]
