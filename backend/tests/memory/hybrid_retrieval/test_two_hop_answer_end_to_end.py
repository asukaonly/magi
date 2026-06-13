"""End-to-end test: 2-hop answer edge survives fusion and appears in projected output.

Scenario (S7): "谁是我同事的老板？" (Who is my colleague's boss?)
- user:me WORKS_WITH person:zs  (hop1, structured_graph)
- person:zs REPORTS_TO person:ls (hop2, structured_graph, object_type=person, _hop=2)
- 18 user-subject edge_vector noise edges (LIKES/USES/INTERESTED_IN/…, _subject_match_score=1.0)

The hop2 answer edge must survive fuse_l2_candidates (top_k=40, mirroring
limit=20 × 2 as l2_query_execution does) and appear in project_candidates's
``relationships`` output.

This test is purely in-process — no live DB required.
"""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.grounding import (
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.models import TemporalContext
from magi.memory.hybrid_retrieval.l2_fusion import (
    fuse_l2_candidates,
    project_candidates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(**kwargs) -> L2GroundingPlan:
    defaults = {
        "query_kind": "exact_fact",
        "subject_scope": "self",
        "subject_candidates": [
            GroundedEntityCandidate(
                entity_id="user:me",
                entity_type="person",
                surface="self",
                score=1.0,
            )
        ],
        "predicate_candidates": [
            GroundedPredicateCandidate(predicate="WORKS_WITH", family="org"),
            GroundedPredicateCandidate(predicate="REPORTS_TO", family="org"),
        ],
        "temporal_context": TemporalContext(mode="none"),
        "hop2_target_type": "person",
    }
    defaults.update(kwargs)
    return L2GroundingPlan(**defaults)


def _make_noise_edge(i: int) -> dict:
    """High-volume user-subject edge_vector noise edge (good subject match, off-predicate)."""
    predicate = ["LIKES", "USES", "INTERESTED_IN", "KNOWS", "OWNS", "HAS_SKILL",
                 "VISITED", "WANTS", "FOLLOWS", "RATED", "REVIEWED", "WATCHES",
                 "READS", "PLAYS", "LISTENS_TO", "SUBSCRIBES_TO", "SAVES", "SHARES"][i % 18]
    return {
        "triple_id": f"noise-ev-{i}",
        "subject_id": "user:me",
        "predicate": predicate,
        "object_id": f"object:noise-{i}",
        "object_type": "thing",
        "_hop": 1,
        "_subject_match_score": 1.0,    # perfect subject match — mimics user-centric pull
        "_predicate_match_score": 0.15,  # off-predicate
        "_object_constraint_score": 0.2,
        "_temporal_score": 1.0,
        "status": "active",
        "confidence": 0.75,
        "observation_count": 2,
        "vector_distance": 0.35,         # decent vector similarity
        "_channels": ["edge_vector"],
    }


# ---------------------------------------------------------------------------
# The answer edges
# ---------------------------------------------------------------------------

HOP1_EDGE = {
    "triple_id": "hop1-works-with-zs",
    "subject_id": "user:me",
    "predicate": "WORKS_WITH",
    "object_id": "person:zs",
    "object_type": "person",
    "_hop": 1,
    "_subject_match_score": 1.0,
    "_predicate_match_score": 1.0,
    "_object_constraint_score": 1.0,
    "_temporal_score": 1.0,
    "status": "active",
    "confidence": 0.9,
    "observation_count": 3,
    "_channels": ["structured_graph"],
}

HOP2_ANSWER_EDGE = {
    "triple_id": "hop2-reports-to-ls",
    "subject_id": "person:zs",       # bridge subject — NOT the user
    "predicate": "REPORTS_TO",
    "object_id": "person:ls",
    "object_type": "person",          # matches plan.hop2_target_type → IS the answer
    "_hop": 2,
    "_subject_match_score": 0.0,      # bridge hop: subject is colleague, not user
    "_predicate_match_score": 1.0,
    "_object_constraint_score": 1.0,
    "_temporal_score": 1.0,
    "status": "active",
    "confidence": 0.85,
    "observation_count": 2,
    "_channels": ["structured_graph"],
}


# ---------------------------------------------------------------------------
# End-to-end test
# ---------------------------------------------------------------------------

def test_two_hop_answer_survives_fusion_and_projection():
    """The hop2 answer edge (person:zs REPORTS_TO person:ls) must survive top_k
    fusion and appear in the projected ``relationships`` output even when flooded
    by 18 high-subject-match edge_vector noise edges.

    top_k=40 mirrors l2_query_execution's limit=20 × 2.
    """
    plan = _make_plan()

    noise_edges = [_make_noise_edge(i) for i in range(18)]
    all_edges = [HOP1_EDGE, HOP2_ANSWER_EDGE] + noise_edges

    # --- fuse ---
    candidates = fuse_l2_candidates(
        plan,
        knowledge_edges=all_edges,
        assertions=[],
        snapshots=[],
        episodes=[],
        top_k=40,   # limit=20 × 2 (mirrors l2_query_execution)
    )

    assert candidates, "fuse_l2_candidates returned no candidates at all"

    candidate_ids = [c.candidate_id for c in candidates]

    # The hop2 answer edge must survive the fusion cut
    assert "hop2-reports-to-ls" in candidate_ids, (
        f"hop2 answer edge (person:zs REPORTS_TO person:ls) was dropped by fusion.\n"
        f"Candidate IDs in result: {candidate_ids}\n"
        f"Scores: { {c.candidate_id: c.final_score for c in candidates} }"
    )

    # --- project ---
    projected = project_candidates(candidates)

    relationship_ids = [r.get("triple_id") for r in projected["relationships"]]

    assert "hop2-reports-to-ls" in relationship_ids, (
        f"hop2 answer edge was present after fusion but missing from projected relationships.\n"
        f"Projected relationship IDs: {relationship_ids}"
    )

    # Also confirm the projected edge has the right structure
    answer_rel = next(
        r for r in projected["relationships"] if r.get("triple_id") == "hop2-reports-to-ls"
    )
    assert answer_rel["object_id"] == "person:ls", (
        f"Projected answer edge has wrong object_id: {answer_rel['object_id']}"
    )
    assert answer_rel["predicate"] == "REPORTS_TO", (
        f"Projected answer edge has wrong predicate: {answer_rel['predicate']}"
    )
    assert answer_rel["_hop"] == 2, (
        f"Projected answer edge should be tagged _hop=2, got: {answer_rel.get('_hop')}"
    )


def test_hop1_bridge_edge_also_survives():
    """The hop1 WORKS_WITH edge (user:me → person:zs) must also survive — it
    is the bridge that makes the hop2 answer meaningful."""
    plan = _make_plan()

    noise_edges = [_make_noise_edge(i) for i in range(18)]
    all_edges = [HOP1_EDGE, HOP2_ANSWER_EDGE] + noise_edges

    candidates = fuse_l2_candidates(
        plan,
        knowledge_edges=all_edges,
        assertions=[],
        snapshots=[],
        episodes=[],
        top_k=40,
    )

    candidate_ids = [c.candidate_id for c in candidates]
    assert "hop1-works-with-zs" in candidate_ids, (
        f"hop1 bridge edge (user:me WORKS_WITH person:zs) was dropped.\n"
        f"Candidate IDs: {candidate_ids}"
    )


def test_hop2_answer_ranks_above_most_noise():
    """The hop2 answer edge should rank in the top third of results (not last)."""
    plan = _make_plan()

    noise_edges = [_make_noise_edge(i) for i in range(18)]
    all_edges = [HOP1_EDGE, HOP2_ANSWER_EDGE] + noise_edges

    candidates = fuse_l2_candidates(
        plan,
        knowledge_edges=all_edges,
        assertions=[],
        snapshots=[],
        episodes=[],
        top_k=40,
    )

    ids = [c.candidate_id for c in candidates]
    answer_rank = ids.index("hop2-reports-to-ls")
    n = len(ids)

    assert answer_rank < n * 2 // 3, (
        f"hop2 answer edge ranked {answer_rank}/{n} — expected in top two-thirds.\n"
        f"Scores: { {c.candidate_id: c.final_score for c in candidates} }"
    )
