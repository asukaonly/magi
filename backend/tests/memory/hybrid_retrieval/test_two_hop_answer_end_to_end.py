"""Retrieve a persisted two-hop answer and retain it under simulated vector competition."""

import time
import pytest
from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.l2.store import L2CognitionStore
from magi.memory.hybrid_retrieval.grounding import (
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.models import TemporalContext
from magi.memory.hybrid_retrieval.l2_knowledge_retriever import retrieve_knowledge
from magi.memory.hybrid_retrieval.l2_fusion import fuse_l2_candidates, project_candidates


@pytest.mark.asyncio
async def test_persisted_two_hop_answer_survives_actual_fusion_truncation(tmp_path):
    path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(path)
    store = L2CognitionStore(db_path=path)
    await store.initialize()

    async def seed(subject, predicate, target, kind, confidence):
        return await store.upsert_knowledge_edge(
            subject_id=subject,
            subject_type="person",
            predicate=predicate,
            object_id=target,
            object_type=kind,
            evidence_event_ids=[f"event:{target}"],
            confidence=confidence,
            observed_at=time.time(),
            source_type="conversation",
        )

    bridge = await seed("user:me", "WORKS_WITH", "person:zs", "person", 0.9)
    answer = await seed("person:zs", "REPORTS_TO", "person:ls", "person", 0.85)
    for index in range(18):
        await seed("user:me", "USES", f"object:noise-{index}", "thing", 0.75)
    plan = L2GroundingPlan(
        query_kind="exact_fact",
        subject_scope="self",
        subject_candidates=[
            GroundedEntityCandidate(
                entity_id="user:me", entity_type="person", surface="self", score=1.0
            )
        ],
        predicate_candidates=[
            GroundedPredicateCandidate(predicate="WORKS_WITH", family="org"),
            GroundedPredicateCandidate(predicate="REPORTS_TO", family="org"),
        ],
        temporal_context=TemporalContext(mode="none"),
        hop2_target_type="person",
        allow_soft_edges=False,
    )
    graph = await retrieve_knowledge(plan, store, limit=20)
    assert {edge["triple_id"] for edge in graph} == {bridge, answer}
    noise = await store.get_relationships(subject_id="user:me", predicates=["USES"], limit=30)
    assert len(noise) == 18
    # Simulate vector-channel scores on persisted distractors without a live encoder.
    for edge in noise:
        edge.update(
            _channels=["edge_vector"],
            _subject_match_score=1.0,
            _predicate_match_score=0.15,
            _object_constraint_score=0.2,
            _temporal_score=1.0,
            _hop=1,
            vector_distance=0.35,
        )
    candidates = fuse_l2_candidates(
        plan, knowledge_edges=noise + graph, assertions=[], snapshots=[], episodes=[], top_k=6
    )
    ids = [candidate.candidate_id for candidate in candidates]
    assert len(ids) == len(set(ids)) == 6
    assert bridge in ids
    assert ids.index(answer) < 2
    projected = project_candidates(candidates)["relationships"]
    assert [edge["triple_id"] for edge in projected] == ids
    by_id = {edge["triple_id"]: edge for edge in projected}
    assert (
        by_id[bridge]["subject_id"],
        by_id[bridge]["predicate"],
        by_id[bridge]["object_id"],
    ) == ("user:me", "WORKS_WITH", "person:zs")
    assert (
        by_id[answer]["subject_id"],
        by_id[answer]["predicate"],
        by_id[answer]["object_id"],
        by_id[answer]["_hop"],
    ) == ("person:zs", "REPORTS_TO", "person:ls", 2)
    assert by_id[answer]["_fusion_score"] == next(
        candidate.final_score for candidate in candidates if candidate.candidate_id == answer
    )
