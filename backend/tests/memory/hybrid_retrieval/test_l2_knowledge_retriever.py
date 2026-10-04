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
    async def test_creator_recall_preserves_returned_presence_and_evidence_policy(self):
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

        results = await retrieve_knowledge(plan, store)
        assert [(e["subject_id"], e["predicate"], e["object_id"]) for e in results] == [
            ("user:u1", "FOLLOWS", "presence:p1")
        ]
        assert "_resolved_identity" not in results[0]

        presence_of_calls = [
            c
            for c in store.batch_get_relationships.await_args_list
            if c.kwargs.get("predicates") == ["PRESENCE_OF"]
        ]
        non_presence_of_calls = [
            c
            for c in store.batch_get_relationships.await_args_list
            if c.kwargs.get("predicates") != ["PRESENCE_OF"]
        ]

        # Bridge resolution removed — no PRESENCE_OF call should be issued.
        assert not presence_of_calls, (
            "PRESENCE_OF identity-bridge call should no longer fire; " f"got {presence_of_calls}"
        )
        assert non_presence_of_calls, "expected at least one recall-path call"
        # Soft-edge sparse-fallback calls (predicates=["SEMANTIC_CONTEXT"]) are
        # intentionally exempt from evidence_classes forwarding (RFC #65 P2).
        recall_calls = [
            c for c in non_presence_of_calls if c.kwargs.get("predicates") != ["SEMANTIC_CONTEXT"]
        ]
        assert recall_calls, "expected at least one primary recall-path call"
        for call in recall_calls:
            assert call.kwargs.get("evidence_classes") == [
                EvidenceClass.USER_SELF_REPORT.label
            ], f"recall-path call must forward evidence_classes; got {call}"

    @pytest.mark.asyncio
    async def test_explicit_object_grounding_excludes_other_places(self, seeded_l2_store):
        from magi.memory.hybrid_retrieval.grounding import build_grounding_plan
        from magi.memory.hybrid_retrieval.models import L2Conditions, L2SemanticFrame

        store = seeded_l2_store
        for place in ["shanghai", "beijing"]:
            await store.upsert_knowledge_edge(
                subject_id="user:u1",
                subject_type="person",
                predicate="LIKES",
                object_id="place:" + place,
                object_type="place",
                evidence_event_ids=["event:" + place],
                confidence=0.9,
                observed_at=1700000000,
                source_type="chat",
                evidence_class=EvidenceClass.USER_SELF_REPORT.label,
            )
        plan = build_grounding_plan(
            L2Conditions(
                content_query="Do I like Shanghai?",
                predicates=["LIKES"],
                allow_soft_edges=False,
                semantic_frame=L2SemanticFrame(
                    query_family="affinity",
                    subject_scope="self",
                    answer_kind="place",
                    object_mentions=["Shanghai"],
                ),
            ),
            resolved_entities=[
                {
                    "entity_id": "place:shanghai",
                    "entity_type": "place",
                    "canonical_name": "Shanghai",
                    "confidence": 1.0,
                }
            ],
            user_id="u1",
        )
        merged = await retrieve_knowledge(plan, store)
        assert [(e["subject_id"], e["predicate"], e["object_id"]) for e in merged] == [
            ("user:u1", "LIKES", "place:shanghai")
        ]


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
@pytest.mark.parametrize("allow_soft", [False, True])
async def test_grounded_soft_edge_policy_changes_real_retrieval(seeded_l2_store, allow_soft):
    from magi.memory.hybrid_retrieval.grounding import build_grounding_plan
    from magi.memory.hybrid_retrieval.models import L2Conditions

    store = seeded_l2_store
    for predicate, object_id, object_type, fact_kind in [
        ("LIKES", "person:artist", "person", None),
        ("SEMANTIC_CONTEXT", "topic:music", "concept", "semantic_edge"),
    ]:
        await store.upsert_knowledge_edge(
            subject_id="user:u1",
            subject_type="person",
            predicate=predicate,
            object_id=object_id,
            object_type=object_type,
            fact_kind=fact_kind,
            evidence_event_ids=["event:" + object_id],
            confidence=0.9,
            observed_at=1700000000,
            source_type="chat",
            evidence_class=EvidenceClass.USER_SELF_REPORT.label,
        )
    plan = build_grounding_plan(
        L2Conditions(
            content_query="liked artists",
            subject_hint="self",
            predicates=["LIKES"],
            allow_soft_edges=allow_soft,
        ),
        resolved_entities=[],
        user_id="u1",
    )
    merged = await retrieve_knowledge(plan, store)
    assert {e["object_id"] for e in merged} == (
        {"person:artist", "topic:music"} if allow_soft else {"person:artist"}
    )
    assert len(merged) == (2 if allow_soft else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("target_type", [None, "media"])
async def test_grounded_hop2_target_selects_album_and_excludes_place(seeded_l2_store, target_type):
    from magi.memory.hybrid_retrieval.grounding import build_grounding_plan
    from magi.memory.hybrid_retrieval.models import L2Conditions

    store = seeded_l2_store
    for subject, predicate, target, target_kind in [
        ("user:u1", "LIKES", "person:artist", "person"),
        ("person:artist", "CREATES", "media:album", "media"),
        ("person:artist", "VISITED", "place:studio", "place"),
    ]:
        await store.upsert_knowledge_edge(
            subject_id=subject,
            subject_type="person",
            predicate=predicate,
            object_id=target,
            object_type=target_kind,
            evidence_event_ids=["event:" + target],
            confidence=0.9,
            observed_at=1700000000,
            source_type="chat",
            evidence_class=EvidenceClass.USER_SELF_REPORT.label,
        )
    plan = build_grounding_plan(
        L2Conditions(
            content_query="albums of liked artists",
            subject_hint="self",
            predicates=["LIKES"],
            hop2_target_type=target_type,
            allow_soft_edges=False,
        ),
        resolved_entities=[],
        user_id="u1",
    )
    merged = await retrieve_knowledge(plan, store)
    assert {e["object_id"] for e in merged} == (
        {"person:artist", "media:album"} if target_type else {"person:artist"}
    )
    assert len(merged) == (2 if target_type else 1)
    if target_type:
        album = next(e for e in merged if e["object_id"] == "media:album")
        assert album["_hop"] == 2
        assert album["object_type"] == "media"


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
                    "source_type": "external_source",
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
