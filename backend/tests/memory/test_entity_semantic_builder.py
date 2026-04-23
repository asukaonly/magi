"""Tests for P3-8: Entity-Scoped Semantic Edges.

Covers:
- EntityScopedSemanticBuilder core logic
- cosine_similarity computation
- Cross-entity pair selection
- Config-gated enablement
- L1EventStore.get_event_vectors / get_entity_event_ids / get_event_entity_ids
"""

from __future__ import annotations

import json
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.memory.hybrid_retrieval.entity_semantic_builder import (
    EntityScopedSemanticBuilder,
    cosine_similarity,
    _select_cross_entity_pairs,
    _type_from_id,
    SEMANTIC_EDGE_PREDICATE,
    SEMANTIC_EDGE_FACT_KIND,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_l1_store(
    entity_events: dict[str, list[str]] | None = None,
    event_entities: dict[str, list[str]] | None = None,
    event_vectors: dict[str, list[float]] | None = None,
) -> AsyncMock:
    store = AsyncMock()

    async def get_entity_event_ids(entity_ids, *, limit_per_entity=20):
        mapping = entity_events or {}
        return {eid: mapping.get(eid, []) for eid in entity_ids}

    async def get_event_entity_ids(event_ids):
        mapping = event_entities or {}
        return {eid: mapping.get(eid, []) for eid in event_ids}

    async def get_event_vectors(event_ids):
        vecs = event_vectors or {}
        return {eid: vecs[eid] for eid in event_ids if eid in vecs}

    store.get_entity_event_ids = AsyncMock(side_effect=get_entity_event_ids)
    store.get_event_entity_ids = AsyncMock(side_effect=get_event_entity_ids)
    store.get_event_vectors = AsyncMock(side_effect=get_event_vectors)
    return store


def _mock_l2_store() -> AsyncMock:
    store = AsyncMock()
    store.upsert_knowledge_edge = AsyncMock(return_value="triple_123")
    return store


def _make_vec(dim: int, value: float) -> list[float]:
    """Create a uniform vector of given dimension and value."""
    return [value] * dim


# ---------------------------------------------------------------------------
# cosine_similarity tests
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector(self):
        a = [0.0, 0.0]
        b = [1.0, 2.0]
        assert cosine_similarity(a, b) == 0.0

    def test_similar_vectors(self):
        a = [1.0, 2.0, 3.0]
        b = [1.1, 2.1, 3.1]
        sim = cosine_similarity(a, b)
        assert sim > 0.99


# ---------------------------------------------------------------------------
# _type_from_id tests
# ---------------------------------------------------------------------------


class TestTypeFromId:
    def test_prefixed_id(self):
        assert _type_from_id("person:abc123") == "person"

    def test_unprefixed_id(self):
        assert _type_from_id("unknown") == "entity"

    def test_multi_colon(self):
        assert _type_from_id("concept:ai:ml") == "concept"


# ---------------------------------------------------------------------------
# _select_cross_entity_pairs tests
# ---------------------------------------------------------------------------


class TestSelectCrossEntityPairs:
    def test_both_sides_have_unique(self):
        pairs = _select_cross_entity_pairs(
            new_only={"person:alice"},
            sib_only={"place:tokyo"},
            shared={"concept:ai"},
        )
        assert len(pairs) == 1
        assert pairs[0][:2] == ("person:alice", "place:tokyo")

    def test_only_new_unique(self):
        pairs = _select_cross_entity_pairs(
            new_only={"person:alice"},
            sib_only=set(),
            shared={"concept:ai"},
        )
        assert len(pairs) == 1
        assert pairs[0][0] == "person:alice"
        assert pairs[0][1] == "concept:ai"

    def test_only_sib_unique(self):
        pairs = _select_cross_entity_pairs(
            new_only=set(),
            sib_only={"place:tokyo"},
            shared={"concept:ai"},
        )
        assert len(pairs) == 1
        assert pairs[0][1] == "place:tokyo"

    def test_all_shared_no_pairs(self):
        pairs = _select_cross_entity_pairs(
            new_only=set(),
            sib_only=set(),
            shared={"concept:ai"},
        )
        assert len(pairs) == 0

    def test_cartesian_product(self):
        pairs = _select_cross_entity_pairs(
            new_only={"a", "b"},
            sib_only={"c", "d"},
            shared={"e"},
        )
        assert len(pairs) == 4  # 2 * 2


# ---------------------------------------------------------------------------
# EntityScopedSemanticBuilder tests
# ---------------------------------------------------------------------------


class TestEntityScopedSemanticBuilder:
    @pytest.mark.asyncio
    async def test_no_entities_returns_zero(self):
        builder = EntityScopedSemanticBuilder(
            l1_store=_mock_l1_store(),
            l2_store=_mock_l2_store(),
        )
        count = await builder.build_edges_for_event("evt1", [], observed_at=1000.0)
        assert count == 0

    @pytest.mark.asyncio
    async def test_no_siblings_returns_zero(self):
        l1 = _mock_l1_store(
            entity_events={"person:alice": ["evt1"]},  # only the new event itself
            event_vectors={"evt1": _make_vec(4, 1.0)},
        )
        builder = EntityScopedSemanticBuilder(l1_store=l1, l2_store=_mock_l2_store())
        count = await builder.build_edges_for_event(
            "evt1", ["person:alice"], observed_at=1000.0,
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_below_threshold_no_edges(self):
        # Two orthogonal vectors → similarity ≈ 0
        l1 = _mock_l1_store(
            entity_events={"person:alice": ["evt1", "evt2"]},
            event_entities={
                "evt1": ["person:alice", "concept:python"],
                "evt2": ["person:alice", "concept:java"],
            },
            event_vectors={
                "evt1": [1.0, 0.0, 0.0, 0.0],
                "evt2": [0.0, 0.0, 0.0, 1.0],
            },
        )
        l2 = _mock_l2_store()
        builder = EntityScopedSemanticBuilder(
            l1_store=l1, l2_store=l2, similarity_threshold=0.8,
        )
        count = await builder.build_edges_for_event(
            "evt1", ["person:alice"], observed_at=1000.0,
        )
        assert count == 0
        l2.upsert_knowledge_edge.assert_not_called()

    @pytest.mark.asyncio
    async def test_above_threshold_creates_edges(self):
        # Two similar vectors → high similarity
        l1 = _mock_l1_store(
            entity_events={"person:alice": ["evt1", "evt2"]},
            event_entities={
                "evt1": ["person:alice", "concept:python"],
                "evt2": ["person:alice", "concept:java"],
            },
            event_vectors={
                "evt1": [1.0, 1.0, 1.0, 1.0],
                "evt2": [1.0, 1.0, 1.0, 0.9],  # very similar
            },
        )
        l2 = _mock_l2_store()
        builder = EntityScopedSemanticBuilder(
            l1_store=l1, l2_store=l2, similarity_threshold=0.5,
        )
        count = await builder.build_edges_for_event(
            "evt1", ["person:alice"], observed_at=1000.0,
        )
        assert count >= 1
        l2.upsert_knowledge_edge.assert_called()
        # Verify the edge parameters
        call_kwargs = l2.upsert_knowledge_edge.call_args.kwargs
        assert call_kwargs["predicate"] == SEMANTIC_EDGE_PREDICATE
        assert call_kwargs["fact_kind"] == SEMANTIC_EDGE_FACT_KIND
        assert "evt1" in call_kwargs["evidence_event_ids"]
        assert "evt2" in call_kwargs["evidence_event_ids"]

    @pytest.mark.asyncio
    async def test_config_disabled_skips(self):
        """When config says disabled, no edges should be built."""
        config = MagicMock()
        config.agent.memory.entity_semantic_edges.enabled = False
        config.agent.memory.entity_semantic_edges.similarity_threshold = 0.75
        config.agent.memory.entity_semantic_edges.max_sibling_events = 20
        config.agent.memory.entity_semantic_edges.max_edges_per_event = 10

        l1 = _mock_l1_store(
            entity_events={"person:alice": ["evt1", "evt2"]},
            event_vectors={
                "evt1": [1.0, 1.0],
                "evt2": [1.0, 1.0],
            },
        )
        l2 = _mock_l2_store()
        builder = EntityScopedSemanticBuilder(
            l1_store=l1, l2_store=l2,
            config_getter=lambda: config,
        )
        count = await builder.build_edges_for_event(
            "evt1", ["person:alice"], observed_at=1000.0,
        )
        assert count == 0
        l2.upsert_knowledge_edge.assert_not_called()

    @pytest.mark.asyncio
    async def test_config_enabled_builds_edges(self):
        """When config says enabled, edges should be built."""
        config = MagicMock()
        config.agent.memory.entity_semantic_edges.enabled = True
        config.agent.memory.entity_semantic_edges.similarity_threshold = 0.5
        config.agent.memory.entity_semantic_edges.max_sibling_events = 20
        config.agent.memory.entity_semantic_edges.max_edges_per_event = 10

        l1 = _mock_l1_store(
            entity_events={"person:alice": ["evt1", "evt2"]},
            event_entities={
                "evt1": ["person:alice", "concept:python"],
                "evt2": ["person:alice", "concept:java"],
            },
            event_vectors={
                "evt1": [1.0, 1.0, 1.0],
                "evt2": [1.0, 1.0, 0.9],
            },
        )
        l2 = _mock_l2_store()
        builder = EntityScopedSemanticBuilder(
            l1_store=l1, l2_store=l2,
            config_getter=lambda: config,
        )
        count = await builder.build_edges_for_event(
            "evt1", ["person:alice"], observed_at=1000.0,
        )
        assert count >= 1

    @pytest.mark.asyncio
    async def test_memory_settings_object_disables_edges_without_root_config_wrapper(self):
        """The builder should accept a direct memory settings object from lifecycle wiring."""
        memory_cfg = MagicMock()
        memory_cfg.entity_semantic_edges.enabled = False
        memory_cfg.entity_semantic_edges.similarity_threshold = 0.75
        memory_cfg.entity_semantic_edges.max_sibling_events = 20
        memory_cfg.entity_semantic_edges.max_edges_per_event = 10

        l1 = _mock_l1_store(
            entity_events={"person:alice": ["evt1", "evt2"]},
            event_vectors={
                "evt1": [1.0, 1.0],
                "evt2": [1.0, 1.0],
            },
        )
        l2 = _mock_l2_store()
        builder = EntityScopedSemanticBuilder(
            l1_store=l1,
            l2_store=l2,
            config_getter=lambda: memory_cfg,
        )

        count = await builder.build_edges_for_event(
            "evt1", ["person:alice"], observed_at=1000.0,
        )

        assert count == 0
        l2.upsert_knowledge_edge.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_embedding_returns_zero(self):
        """When the new event has no embedding, skip gracefully."""
        l1 = _mock_l1_store(
            entity_events={"person:alice": ["evt1", "evt2"]},
            event_vectors={"evt2": [1.0, 1.0]},  # evt1 has no vector
        )
        builder = EntityScopedSemanticBuilder(
            l1_store=l1, l2_store=_mock_l2_store(),
        )
        count = await builder.build_edges_for_event(
            "evt1", ["person:alice"], observed_at=1000.0,
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_max_edges_cap(self):
        """Should not create more edges than max_edges_per_event."""
        # Create many siblings all very similar
        sibs = [f"sib{i}" for i in range(10)]
        l1 = _mock_l1_store(
            entity_events={"person:alice": ["evt1"] + sibs},
            event_entities={
                **{"evt1": ["person:alice", "concept:new"]},
                **{s: ["person:alice", f"concept:s{i}"] for i, s in enumerate(sibs)},
            },
            event_vectors={
                **{"evt1": [1.0, 1.0, 1.0, 1.0]},
                **{s: [1.0, 1.0, 1.0, 0.99] for s in sibs},
            },
        )
        l2 = _mock_l2_store()
        builder = EntityScopedSemanticBuilder(
            l1_store=l1, l2_store=l2,
            similarity_threshold=0.5,
            max_edges_per_event=3,
        )
        count = await builder.build_edges_for_event(
            "evt1", ["person:alice"], observed_at=1000.0,
        )
        assert count <= 3

    @pytest.mark.asyncio
    async def test_l2_error_handled_gracefully(self):
        """upsert_knowledge_edge failures should not crash the builder."""
        l1 = _mock_l1_store(
            entity_events={"person:alice": ["evt1", "evt2"]},
            event_entities={
                "evt1": ["person:alice", "concept:python"],
                "evt2": ["person:alice", "concept:java"],
            },
            event_vectors={
                "evt1": [1.0, 1.0, 1.0],
                "evt2": [1.0, 1.0, 0.9],
            },
        )
        l2 = _mock_l2_store()
        l2.upsert_knowledge_edge = AsyncMock(side_effect=RuntimeError("db error"))

        builder = EntityScopedSemanticBuilder(
            l1_store=l1, l2_store=l2,
            similarity_threshold=0.5,
        )
        # Should not raise
        count = await builder.build_edges_for_event(
            "evt1", ["person:alice"], observed_at=1000.0,
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_multiple_entities_finds_cross_connections(self):
        """Events sharing different entities should still produce edges."""
        l1 = _mock_l1_store(
            entity_events={
                "person:alice": ["evt1", "evt2"],
                "concept:ai": ["evt1", "evt3"],
            },
            event_entities={
                "evt1": ["person:alice", "concept:ai"],
                "evt2": ["person:alice", "place:tokyo"],
                "evt3": ["concept:ai", "concept:robotics"],
            },
            event_vectors={
                "evt1": [1.0, 1.0, 1.0],
                "evt2": [0.9, 1.0, 1.0],  # similar to evt1
                "evt3": [1.0, 0.9, 1.0],  # similar to evt1
            },
        )
        l2 = _mock_l2_store()
        builder = EntityScopedSemanticBuilder(
            l1_store=l1, l2_store=l2,
            similarity_threshold=0.5,
        )
        count = await builder.build_edges_for_event(
            "evt1", ["person:alice", "concept:ai"], observed_at=1000.0,
        )
        assert count >= 2  # edges from evt2 and evt3


# ---------------------------------------------------------------------------
# Config model tests
# ---------------------------------------------------------------------------


class TestEntitySemanticEdgeConfig:
    def test_settings_defaults(self):
        from magi.config.models import EntitySemanticEdgeSettings

        s = EntitySemanticEdgeSettings()
        assert s.enabled is False

    def test_memory_settings_includes_field(self):
        from magi.config.models import MemorySettings

        m = MemorySettings()
        assert hasattr(m, "entity_semantic_edges")
        assert m.entity_semantic_edges.enabled is False
