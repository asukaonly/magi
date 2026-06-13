"""Tests that a hop2 answer edge (object_type matches plan.hop2_target_type) is NOT
decayed by HOP2_DECAY and ranks above 1-hop noise edges.

Scenario: query "我同事的老板是谁" (who is my colleague's boss?)
- plan.hop2_target_type = "person"  (the answer type we expect)
- answer edge: 张三 REPORTS_TO 李四, _hop=2, object_type="person", channel=structured_graph
- noise edges: 6 user-subject edges (USES, LIKES, etc.), _hop=1, subject=user,
  _subject_match_score=1.0, off-predicate, with vector_distance

The answer edge must rank at position 0 or 1 (near top), not last.
"""

import pytest

from magi.memory.hybrid_retrieval.grounding import (
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.models import TemporalContext
from magi.memory.hybrid_retrieval.l2_fusion import (
    L2Candidate,
    _compute_final_score,
    fuse_l2_candidates,
)


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
            GroundedPredicateCandidate(predicate="REPORTS_TO", family="org"),
        ],
        "temporal_context": TemporalContext(mode="none"),
        "hop2_target_type": "person",
    }
    defaults.update(kwargs)
    return L2GroundingPlan(**defaults)


# ---------------------------------------------------------------------------
# Unit test: _compute_final_score hop2 answer vs hop2 non-answer
# ---------------------------------------------------------------------------

def test_hop2_answer_edge_not_decayed():
    """hop2 edge whose object_type matches hop2_target_type must NOT be decayed
    (its score must be >= an otherwise-identical hop2 edge that is NOT the answer)."""
    plan = _make_plan()

    answer = L2Candidate(
        candidate_id="answer",
        kind="knowledge_edge",
        payload={"_hop": 2, "object_type": "person", "_channel": "structured_graph"},
        subject_match_score=0.0,  # no direct user-subject match (bridge hop)
        predicate_match_score=1.0,
        object_constraint_score=1.0,
        status_score=1.0,
        confidence_score=0.85,
        retrieval_channels=["structured_graph"],
    )

    speculative = L2Candidate(
        candidate_id="speculative",
        kind="knowledge_edge",
        payload={"_hop": 2, "object_type": "company", "_channel": "structured_graph"},
        subject_match_score=0.0,
        predicate_match_score=1.0,
        object_constraint_score=1.0,
        status_score=1.0,
        confidence_score=0.85,
        retrieval_channels=["structured_graph"],
    )

    answer_score = _compute_final_score(answer, plan)
    speculative_score = _compute_final_score(speculative, plan)

    # Answer edge must score strictly higher than the speculative one
    # (speculative gets HOP2_DECAY=0.5, answer must NOT)
    assert answer_score > speculative_score, (
        f"answer edge ({answer_score:.4f}) should outrank speculative hop2 edge ({speculative_score:.4f})"
    )


def test_hop2_non_answer_still_decayed():
    """hop2 edge whose object_type does NOT match hop2_target_type must STILL be decayed
    (regression: we must not remove the decay for speculative inferences)."""
    plan = _make_plan(hop2_target_type="person")

    speculative = L2Candidate(
        candidate_id="speculative",
        kind="knowledge_edge",
        payload={"_hop": 2, "object_type": "company"},
        subject_match_score=0.0,
        predicate_match_score=1.0,
        object_constraint_score=1.0,
        status_score=1.0,
        confidence_score=0.85,
        retrieval_channels=["structured_graph"],
    )

    # Same candidate but hop1 (no decay)
    hop1 = L2Candidate(
        candidate_id="hop1_equiv",
        kind="knowledge_edge",
        payload={"object_type": "company"},
        subject_match_score=1.0,
        predicate_match_score=1.0,
        object_constraint_score=1.0,
        status_score=1.0,
        confidence_score=0.85,
        retrieval_channels=["structured_graph"],
    )

    spec_score = _compute_final_score(speculative, plan)
    hop1_score = _compute_final_score(hop1, plan)
    # Speculative hop2 must be below equivalent hop1 (decay is active)
    assert spec_score < hop1_score, (
        f"speculative hop2 ({spec_score:.4f}) should be decayed below hop1 ({hop1_score:.4f})"
    )


# ---------------------------------------------------------------------------
# Integration test: fuse_l2_candidates — answer edge ranks near top
# ---------------------------------------------------------------------------

def test_hop2_answer_ranks_near_top_in_fusion():
    """Full fusion scenario: 'who is my colleague's boss?'

    One precise answer edge (_hop=2, object_type=person) plus 6 off-predicate
    user-subject noise edges must yield the answer edge in position 0 or 1.
    """
    plan = _make_plan()

    # The precise answer: 张三 REPORTS_TO 李四
    answer_edge = {
        "triple_id": "answer-edge-001",
        "subject_id": "person:zhangsan",  # colleague — not the user
        "predicate": "REPORTS_TO",
        "object_id": "person:lisi",
        "object_type": "person",
        "_hop": 2,
        "_subject_match_score": 0.0,   # bridge hop: subject is colleague
        "_predicate_match_score": 0.9,
        "_object_constraint_score": 1.0,
        "_temporal_score": 1.0,
        "status": "active",
        "confidence": 0.85,
        "_channels": ["structured_graph"],
    }

    # 6 off-predicate noise edges from the user (good subject_match, but wrong predicate)
    noise_edges = []
    noise_predicates = ["USES", "LIKES", "OWNS", "KNOWS", "VISITED", "HAS_SKILL"]
    for i, pred in enumerate(noise_predicates):
        noise_edges.append({
            "triple_id": f"noise-{i}",
            "subject_id": "user:me",
            "predicate": pred,
            "object_id": f"object:{i}",
            "object_type": "thing",
            "_hop": 1,
            "_subject_match_score": 1.0,
            "_predicate_match_score": 0.1,
            "_object_constraint_score": 0.2,
            "_temporal_score": 1.0,
            "status": "active",
            "confidence": 0.8,
            "vector_distance": 0.4,  # decent vector match
            "_channels": ["edge_vector"],
        })

    all_edges = [answer_edge] + noise_edges

    results = fuse_l2_candidates(
        plan,
        knowledge_edges=all_edges,
        assertions=[],
        snapshots=[],
        episodes=[],
        top_k=10,
    )

    assert results, "fuse_l2_candidates returned no results"

    ids = [c.candidate_id for c in results]
    answer_rank = ids.index("answer-edge-001")

    assert answer_rank <= 1, (
        f"Answer edge ranked {answer_rank} (expected 0 or 1). "
        f"Rankings: {list(enumerate(ids))}. "
        f"Scores: { {c.candidate_id: c.final_score for c in results} }"
    )
