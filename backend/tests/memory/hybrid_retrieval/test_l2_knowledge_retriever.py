"""Tests that the L2 knowledge retriever forwards ``allowed_evidence_classes``
from the grounding plan down to the L2 store's relationship queries.

These tests use ``AsyncMock`` rather than seeding a full SQLite DB — the store
contract for the new ``evidence_classes`` kwarg is exercised directly in
``tests/memory/l2/test_retrieval_relationships.py``. Here we only assert that
the retriever passes the kwarg through correctly for each call site.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.evidence import EvidenceClass
from magi.memory.hybrid_retrieval.grounding import (
    GroundedConstraint,
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.l2_knowledge_retriever import retrieve_knowledge
from magi.memory.hybrid_retrieval.models import TemporalContext


def _make_store() -> MagicMock:
    store = MagicMock()
    store.get_relationships = AsyncMock(return_value=[])
    store.batch_get_relationships = AsyncMock(return_value={})
    store.search_edges_by_embedding = AsyncMock(return_value=[])
    store.filter_entity_ids_by_facet = AsyncMock(return_value=[])
    return store


def _plan_with_subject(**overrides) -> L2GroundingPlan:
    plan = L2GroundingPlan(
        query_kind="preference",
        subject_candidates=[
            GroundedEntityCandidate(
                entity_id="user:u1",
                entity_type="person",
                surface="self",
                score=1.0,
                source="rule",
            )
        ],
        predicate_candidates=[
            GroundedPredicateCandidate(predicate="LIKES", family="preference"),
        ],
        temporal_context=TemporalContext(mode="none"),
    )
    for key, value in overrides.items():
        setattr(plan, key, value)
    return plan


class TestBatchForwarding:
    @pytest.mark.asyncio
    async def test_forwards_evidence_classes_when_plan_field_set(self):
        """When ``plan.allowed_evidence_classes`` is set, every recall-path
        ``batch_get_relationships`` call must forward it as a list kwarg.

        Soft-edge sparse-fallback calls (predicates=["SEMANTIC_CONTEXT"]) are
        intentionally exempt — co-occurrence edges lack evidence_class labels.
        """
        store = _make_store()
        plan = _plan_with_subject(
            allowed_evidence_classes={EvidenceClass.USER_SELF_REPORT.label},
        )

        await retrieve_knowledge(plan, store)

        batch_calls = store.batch_get_relationships.await_args_list
        assert batch_calls, "expected at least one batch_get_relationships call"
        # The structured_graph channel is the recall path here; topology is gated
        # behind answer_kind so won't fire for plain "preference".
        # Soft-edge fallback calls use predicates=["SEMANTIC_CONTEXT"] and are
        # deliberately exempt from evidence_classes forwarding (RFC #65 P2).
        recall_calls = [
            c for c in batch_calls
            if c.kwargs.get("predicates") != ["SEMANTIC_CONTEXT"]
        ]
        assert recall_calls, "expected at least one recall-path call"
        for call in recall_calls:
            assert call.kwargs.get("evidence_classes") == [
                EvidenceClass.USER_SELF_REPORT.label
            ], f"forwarding failed in call: {call}"

    @pytest.mark.asyncio
    async def test_omits_evidence_classes_when_plan_field_none(self):
        """When ``plan.allowed_evidence_classes`` is ``None`` (default), the
        retriever must pass ``None`` so the store skips the filter and
        preserves existing behavior for callers that haven't opted in."""
        store = _make_store()
        plan = _plan_with_subject()
        assert plan.allowed_evidence_classes is None

        await retrieve_knowledge(plan, store)

        for call in store.batch_get_relationships.await_args_list:
            assert call.kwargs.get("evidence_classes") is None, (
                "evidence_classes should be None when plan field is unset; "
                f"got {call}"
            )

    @pytest.mark.asyncio
    async def test_creator_topology_runs_recall_only_no_identity_bridge(self):
        """``_topology_creator`` previously issued a second PRESENCE_OF batch
        call to attach a ``_resolved_identity`` sidecar to each primary edge,
        but no production consumer read that field — Phase 5's
        ``entity_catalog`` canonical-name resolution superseded it.

        Contract after dead-code removal:
        * No PRESENCE_OF batch call is issued from the topology executor.
        * Every recall-path call still forwards the plan's evidence_classes.
        """
        store = _make_store()
        store.batch_get_relationships = AsyncMock(
            return_value={
                "user:u1": [
                    {
                        "triple_id": "t1",
                        "subject_id": "user:u1",
                        "predicate": "FOLLOWS",
                        "object_id": "presence:p1",
                        "object_type": "presence",
                    }
                ]
            }
        )

        plan = _plan_with_subject(
            answer_kind="creator",
            allowed_evidence_classes={EvidenceClass.USER_SELF_REPORT.label},
        )

        await retrieve_knowledge(plan, store)

        presence_of_calls = [
            c for c in store.batch_get_relationships.await_args_list
            if c.kwargs.get("predicates") == ["PRESENCE_OF"]
        ]
        non_presence_of_calls = [
            c for c in store.batch_get_relationships.await_args_list
            if c.kwargs.get("predicates") != ["PRESENCE_OF"]
        ]

        # Bridge resolution removed — no PRESENCE_OF call should be issued.
        assert not presence_of_calls, (
            "PRESENCE_OF identity-bridge call should no longer fire; "
            f"got {presence_of_calls}"
        )
        assert non_presence_of_calls, "expected at least one recall-path call"
        # Soft-edge sparse-fallback calls (predicates=["SEMANTIC_CONTEXT"]) are
        # intentionally exempt from evidence_classes forwarding (RFC #65 P2).
        recall_calls = [
            c for c in non_presence_of_calls
            if c.kwargs.get("predicates") != ["SEMANTIC_CONTEXT"]
        ]
        assert recall_calls, "expected at least one primary recall-path call"
        for call in recall_calls:
            assert call.kwargs.get("evidence_classes") == [
                EvidenceClass.USER_SELF_REPORT.label
            ], f"recall-path call must forward evidence_classes; got {call}"

    @pytest.mark.asyncio
    async def test_structured_graph_uses_explicit_object_entity_as_filter(self):
        store = _make_store()
        plan = _plan_with_subject(
            object_candidates=[
                GroundedEntityCandidate(
                    entity_id="place:shanghai",
                    entity_type="place",
                    surface="Shanghai",
                    score=1.0,
                    source="alias",
                )
            ],
        )

        await retrieve_knowledge(plan, store)

        object_calls = [
            call
            for call in store.get_relationships.await_args_list
            if call.kwargs.get("object_id") == "place:shanghai"
        ]
        assert object_calls, "explicit grounded object entity should narrow the graph query"


class TestSingleEntityForwarding:
    @pytest.mark.asyncio
    async def test_structured_graph_fallback_forwards_evidence_classes(self):
        """When the plan has no subject_ids the structured_graph channel
        falls back to ``get_relationships`` (single-entity / unbounded).
        It must forward ``evidence_classes`` like the batch path."""
        store = _make_store()
        # Build a plan with no subject_candidates so the fallback fires.
        plan = L2GroundingPlan(
            query_kind="preference",
            predicate_candidates=[
                GroundedPredicateCandidate(predicate="LIKES", family="preference"),
            ],
            temporal_context=TemporalContext(mode="none"),
            allowed_evidence_classes={EvidenceClass.USER_SELF_REPORT.label},
        )
        assert not plan.subject_entity_ids

        await retrieve_knowledge(plan, store)

        # The fallback call is the only get_relationships call in this scenario.
        get_calls = store.get_relationships.await_args_list
        assert get_calls, "expected get_relationships fallback to fire"
        for call in get_calls:
            assert call.kwargs.get("evidence_classes") == [
                EvidenceClass.USER_SELF_REPORT.label
            ], f"single-entity fallback must forward evidence_classes; got {call}"

    @pytest.mark.asyncio
    async def test_place_topology_recall_pull_forwards_but_skips_located_in(self):
        """``_topology_place`` issues two kinds of ``get_relationships`` calls:

        - ``LOCATED_IN`` lookup (auxiliary geographic containment, MUST NOT
          carry evidence_classes — geographic facts aren't user_self_reports).
        - VISITED/LIKES recall edges (MUST carry evidence_classes).
        """
        store = _make_store()
        store.get_relationships = AsyncMock(side_effect=[
            # LOCATED_IN result -> one candidate place
            [{"triple_id": "t1", "subject_id": "place:cafe", "object_id": "city:sf"}],
            # VISITED/LIKES recall result
            [],
        ])

        plan = L2GroundingPlan(
            query_kind="preference",
            subject_candidates=[
                GroundedEntityCandidate(
                    entity_id="user:u1", entity_type="person",
                    surface="self", score=1.0, source="rule",
                )
            ],
            predicate_candidates=[
                GroundedPredicateCandidate(predicate="VISITED", family="activity"),
            ],
            answer_kind="place",
            object_constraints=[
                GroundedConstraint(
                    field="located_in",
                    operator="eq",
                    value="city:sf",
                    confidence=1.0,
                ),
            ],
            temporal_context=TemporalContext(mode="none"),
            allowed_evidence_classes={EvidenceClass.USER_SELF_REPORT.label},
        )

        await retrieve_knowledge(plan, store)

        located_in_calls = [
            c for c in store.get_relationships.await_args_list
            if c.kwargs.get("predicates") == ["LOCATED_IN"]
        ]
        recall_calls = [
            c for c in store.get_relationships.await_args_list
            if c.kwargs.get("predicates") != ["LOCATED_IN"]
        ]

        assert located_in_calls, "expected LOCATED_IN auxiliary lookup"
        for call in located_in_calls:
            assert call.kwargs.get("evidence_classes") is None, (
                "LOCATED_IN geographic lookup must NOT carry evidence_classes; "
                f"got {call}"
            )

        assert recall_calls, "expected VISITED/LIKES recall pull"
        for call in recall_calls:
            assert call.kwargs.get("evidence_classes") == [
                EvidenceClass.USER_SELF_REPORT.label
            ], f"place-topology recall must forward evidence_classes; got {call}"


@pytest.mark.asyncio
async def test_topology_channel_skipped_when_no_subject_entity_ids():
    """_topology_channel must abstain (no store call) when the plan has no subject."""
    from magi.memory.hybrid_retrieval.l2_knowledge_retriever import _topology_channel

    store = _make_store()
    plan = L2GroundingPlan(
        query_kind="preference",
        answer_kind="creator",
        temporal_context=TemporalContext(mode="none"),
    )
    assert not plan.subject_entity_ids
    result = await _topology_channel(plan, store)
    assert result == []
    assert store.batch_get_relationships.await_count == 0
    assert store.get_relationships.await_count == 0


@pytest.mark.asyncio
async def test_edge_vector_channel_filters_out_soft_edges():
    """SEMANTIC_CONTEXT must not leak in via the edge_vector channel (RFC #65 P2)."""
    from magi.memory.hybrid_retrieval.l2_knowledge_retriever import _edge_vector_channel

    store = _make_store()
    store.search_edges_by_embedding = AsyncMock(return_value=[
        {"triple_id": "h1", "predicate": "LIKES", "subject_id": "user:u1"},
        {"triple_id": "s1", "predicate": "SEMANTIC_CONTEXT", "subject_id": "user:u1",
         "fact_kind": "semantic_edge"},
    ])

    class _Emb:
        async def embed_text(self, text):
            return object()

    plan = _plan_with_subject()
    results = await _edge_vector_channel(plan, store, _Emb(), object(), limit=20)
    preds = {e["predicate"] for e in results}
    assert "LIKES" in preds
    assert "SEMANTIC_CONTEXT" not in preds


@pytest.mark.asyncio
async def test_structured_channel_soft_fallback_end_to_end():
    """allow_soft_edges → hop1.include_soft_edges → sparse hard → soft edges surface."""
    from magi.memory.hybrid_retrieval.l2_knowledge_retriever import retrieve_knowledge

    store = _make_store()
    store.batch_get_relationships = AsyncMock(side_effect=[
        {"user:u1": []},  # structured hard fetch: empty
        {"user:u1": [{"triple_id": "s1", "subject_id": "user:u1",
                      "predicate": "SEMANTIC_CONTEXT", "object_id": "media:x",
                      "fact_kind": "semantic_edge", "confidence": 0.8}]},  # soft fallback
    ])
    plan = _plan_with_subject(allow_soft_edges=True)
    merged = await retrieve_knowledge(plan, store)
    assert any(e["predicate"] == "SEMANTIC_CONTEXT" for e in merged)


@pytest.mark.asyncio
async def test_structured_channel_no_soft_when_disallowed():
    from magi.memory.hybrid_retrieval.l2_knowledge_retriever import retrieve_knowledge

    store = _make_store()
    store.batch_get_relationships = AsyncMock(return_value={"user:u1": []})
    plan = _plan_with_subject(allow_soft_edges=False)
    await retrieve_knowledge(plan, store)
    for call in store.batch_get_relationships.await_args_list:
        assert call.kwargs.get("predicates") != ["SEMANTIC_CONTEXT"]


@pytest.mark.asyncio
async def test_structured_channel_passes_hop2_to_executor(monkeypatch):
    """plan.hop2_target_type → TraversalPlan.hop2 set + max_hops=2 (captured at executor boundary)."""
    import magi.memory.hybrid_retrieval.l2_knowledge_retriever as mod

    captured = {}

    async def fake_exec(traversal, store, **kwargs):
        captured["hop2"] = traversal.hop2
        captured["max_hops"] = traversal.max_hops
        return []

    monkeypatch.setattr(mod, "execute_graph_traversal", fake_exec)
    store = _make_store()
    plan = _plan_with_subject(hop2_target_type="media")
    await mod._structured_graph_channel(plan, store)
    assert captured["max_hops"] == 2
    assert captured["hop2"] is not None
    assert captured["hop2"].object_types == ("media",)
    assert captured["hop2"].include_soft_edges is True


@pytest.mark.asyncio
async def test_structured_channel_no_hop2_when_target_type_none(monkeypatch):
    import magi.memory.hybrid_retrieval.l2_knowledge_retriever as mod
    captured = {}

    async def fake_exec(traversal, store, **kwargs):
        captured["hop2"] = traversal.hop2
        captured["max_hops"] = traversal.max_hops
        return []

    monkeypatch.setattr(mod, "execute_graph_traversal", fake_exec)
    store = _make_store()
    plan = _plan_with_subject()  # no hop2_target_type
    await mod._structured_graph_channel(plan, store)
    assert captured["hop2"] is None
    assert captured["max_hops"] == 1


@pytest.mark.asyncio
async def test_two_hop_end_to_end_albums_of_liked_artists():
    """Full retrieve_knowledge chain: hop2_target_type=media → hop2 albums surface tagged _hop=2."""
    store = _make_store()
    store.batch_get_relationships = AsyncMock(side_effect=[
        {"user:u1": [{"triple_id": "h1", "subject_id": "user:u1", "predicate": "LIKES",
                      "object_id": "person:artist", "object_type": "person", "confidence": 0.9}]},  # hop1
        {"person:artist": [{"triple_id": "h2", "subject_id": "person:artist",
                            "predicate": "CREATES", "object_id": "media:album",
                            "object_type": "media", "confidence": 0.8}]},  # hop2 hard
        {"person:artist": []},  # hop2 soft
    ])
    plan = _plan_with_subject(hop2_target_type="media", allow_soft_edges=False)
    merged = await retrieve_knowledge(plan, store)
    assert any(e.get("_hop") == 2 and e["object_id"] == "media:album" for e in merged)


@pytest.mark.asyncio
async def test_live_l1_cooccurrence_never_becomes_answer_facing_relationships():
    """Raw co-occurrence is discovery data, not a governed relationship."""
    from magi.memory.hybrid_retrieval.l2_knowledge_retriever import retrieve_knowledge

    class _FakeL1:
        def __init__(self):
            self.cooccurrence_reads = 0

        async def get_entity_event_ids(self, seed_ids, **kw):
            self.cooccurrence_reads += 1
            return {seed_ids[0]: ["e1"]}

        async def get_event_entity_ids(self, event_ids):
            self.cooccurrence_reads += 1
            return {"e1": ["user:u1", "topic:rust"]} if event_ids else {}

    store = _make_store()  # all channels return empty
    plan = _plan_with_subject()
    l1 = _FakeL1()
    merged = await retrieve_knowledge(plan, store, l1_store=l1)

    assert merged == []
    assert l1.cooccurrence_reads == 0


@pytest.mark.asyncio
async def test_filters_knowledge_edges_to_current_user_evidence_scope():
    """Edges backed only by another user's L1 evidence must not leak into L2 recall."""

    class _ScopedL1:
        def __init__(self):
            self.calls = []

        async def filter_ids_by_user(self, event_ids, user_id):
            self.calls.append((list(event_ids), user_id))
            return [event_id for event_id in event_ids if event_id == "evt-local"]

    store = _make_store()
    store.batch_get_relationships = AsyncMock(
        return_value={
            "person:caroline": [
                {
                    "triple_id": "local",
                    "subject_id": "person:caroline",
                    "predicate": "LIKES",
                    "object_id": "topic:abstract-art",
                    "object_type": "topic",
                    "status": "active",
                    "evidence_event_ids": ["evt-local"],
                },
                {
                    "triple_id": "foreign",
                    "subject_id": "person:caroline",
                    "predicate": "LIKES",
                    "object_id": "topic:camping",
                    "object_type": "topic",
                    "status": "active",
                    "evidence_event_ids": ["evt-foreign"],
                },
                {
                    "triple_id": "ungoverned-empty",
                    "subject_id": "person:caroline",
                    "predicate": "LIKES",
                    "object_id": "topic:unverified",
                    "object_type": "topic",
                    "status": "active",
                    "evidence_event_ids": [],
                    "source_type": "external_sensor",
                },
                {
                    "triple_id": "governed-correction",
                    "subject_id": "person:caroline",
                    "predicate": "LIKES",
                    "object_id": "topic:painting",
                    "object_type": "topic",
                    "status": "active",
                    "evidence_event_ids": [],
                    "source_type": "user_correction",
                    "extraction_method": "explicit",
                    "evidence_class": "user_self_report",
                    "authority_ref": "correction:correction-1",
                    "_governed_valid_at": 123.0,
                },
            ]
        }
    )
    plan = _plan_with_subject(
        subject_candidates=[
            GroundedEntityCandidate(
                entity_id="person:caroline",
                entity_type="person",
                surface="Caroline",
                score=1.0,
            )
        ],
        subject_scope="explicit",
    )
    l1 = _ScopedL1()

    merged = await retrieve_knowledge(
        plan,
        store,
        l1_store=l1,
        user_id="benchmark/locomo/run/conv-26",
    )

    assert [edge["triple_id"] for edge in merged] == [
        "local",
        "governed-correction",
    ]
    assert l1.calls == [
        (["evt-local", "evt-foreign"], "benchmark/locomo/run/conv-26")
    ]


def test_l2_handler_holds_l1_store():
    from magi.memory.hybrid_retrieval.l2_handler import L2Handler
    from unittest.mock import MagicMock
    l1 = MagicMock()
    h = L2Handler(MagicMock(), l1_store=l1)
    assert h._l1_store is l1


def test_l2_handler_l1_store_defaults_none():
    from magi.memory.hybrid_retrieval.l2_handler import L2Handler
    from unittest.mock import MagicMock
    h = L2Handler(MagicMock())
    assert h._l1_store is None
