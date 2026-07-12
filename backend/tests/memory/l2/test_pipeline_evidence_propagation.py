"""Phase 1 Task 4: extraction pipeline must propagate `evidence_class`.

These tests target the candidate-builder helpers that construct edge dicts
which eventually become `knowledge_graph` rows via `**candidate` unpacking
in `_upsert_knowledge_edges`. After Task 4, every dict produced by these
helpers must include `evidence_class=classification.evidence_class`.

If the value is missing or `None`, the column on the row will stay NULL
even after Tasks 2-3 added the column and write-path kwarg.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.evidence import EvidenceClass


def _make_user_event(event_id: str = "evt-user-1", content: str = "I like ramen"):
    """Build a MemoryEvent whose classification is USER_SELF_REPORT."""
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "u1",
                "session_id": "s1",
                "content": content,
                "author_type": "user",
                "content_type": "text",
            },
            source="chat",
            level=EventLevel.INFO,
            correlation_id=f"corr-{event_id}",
            timestamp=time.time(),
            event_id=event_id,
        ),
    )


def _classification(label: str) -> SimpleNamespace:
    """Minimal stand-in for `EvidenceClassification` carrying only the label."""
    return SimpleNamespace(evidence_class=label)


def test_fast_track_claims_to_candidates_includes_evidence_class():
    """`_fast_track_claims_to_candidates` must stamp `evidence_class` on every edge dict."""
    from magi.memory.l2.models import L2Phase1FactClaim, L2Phase1Result
    from magi.memory.l2.pipeline import L2Pipeline

    pipeline = L2Pipeline.__new__(L2Pipeline)
    event = _make_user_event(event_id="evt-ft", content="I like ramen")
    classification = _classification(EvidenceClass.USER_SELF_REPORT.label)

    phase1_result = L2Phase1Result(
        entities=[],
        fact_claims=[
            L2Phase1FactClaim(
                subject_ref="user:u1",
                subject_type="user",
                predicate="LIKES",
                object_ref="food:ramen",
                object_type="food",
                fact_kind="explicit_fact",
                confidence=0.9,
                evidence_text="I like ramen",
                supporting_event_ids=["evt-ft"],
            ),
        ],
    )

    profile = SimpleNamespace(
        allow_graph=True,
        effective_structured_allowed_entity_types=frozenset({"food"}),
        effective_structured_allowed_predicates=frozenset({"LIKES"}),
    )

    candidates = pipeline._fast_track_claims_to_candidates(
        phase1_result=phase1_result,
        event=event,
        evidence_event_ids=["evt-ft"],
        resolved_mentions=[],
        catalog_name_index=None,
        profile=profile,
        classification=classification,
    )

    assert len(candidates) == 1
    assert candidates[0]["evidence_class"] == EvidenceClass.USER_SELF_REPORT.label


def test_validate_phase2_graph_edges_includes_evidence_class():
    """`_validate_phase2_graph_edges` must stamp `evidence_class` on prepared edges."""
    from magi.memory.l2.models import L2Phase2GraphEdge
    from magi.memory.l2.ontology import PREDICATE_REGISTRY
    from magi.memory.l2.pipeline import L2Pipeline

    pipeline = L2Pipeline.__new__(L2Pipeline)
    event = _make_user_event(event_id="evt-p2", content="Magi 维护 core-tools 插件")
    classification = _classification(EvidenceClass.USER_SELF_REPORT.label)

    profile = SimpleNamespace(
        allow_graph=True,
        effective_structured_allowed_entity_types=frozenset({"product"}),
        effective_structured_allowed_predicates=PREDICATE_REGISTRY,
    )
    policy = SimpleNamespace(allow_graph_write=True, graph_scope="full")

    prepared, _corroborate, rejected_count = pipeline._validate_phase2_graph_edges(
        event=event,
        profile=profile,
        policy=policy,
        resolved_mentions=[],
        evidence_event_ids=["evt-p2"],
        phase2_edges=[
                L2Phase2GraphEdge(
                subject_ref="user:local_user",
                predicate="MAINTAINS",
                    object_ref="Magi",
                    object_type="product",
                    confidence=0.9,
                    supporting_event_ids=["evt-p2"],
                ),
        ],
        profile_signal_object_refs=set(),
        catalog_name_index={},
        classification=classification,
    )

    assert rejected_count == 0
    assert len(prepared) == 1
    assert prepared[0]["evidence_class"] == EvidenceClass.USER_SELF_REPORT.label


def test_structured_graph_candidates_include_evidence_class():
    """`_build_structured_graph_candidates` must stamp `evidence_class` on prepared edges.

    The direct-write path also persists to `knowledge_graph` (via
    `_direct_write_graph_candidates` → `_upsert_knowledge_edges`), so it must
    carry the evidence_class too.
    """
    from magi.memory.l2.ontology import PREDICATE_REGISTRY
    from magi.memory.l2.pipeline import L2Pipeline

    pipeline = L2Pipeline.__new__(L2Pipeline)
    classification = _classification(EvidenceClass.USER_SELF_REPORT.label)

    # Build an event whose metadata carries a structured_graph_hint that should
    # convert into a direct-write candidate.
    event = _make_user_event(event_id="evt-sgh", content="follow")
    event.metadata_json = {
        "structured_graph_hints": [
            {
                "subject_ref": "user:u1",
                "subject_type": "user",
                "predicate": "FOLLOWS",
                "object_ref": "person:alice",
                "object_type": "person",
                "fact_kind": "public_topology",
                "origin_mode": "source_structured",
                "confidence": 0.95,
            }
        ]
    }

    profile = SimpleNamespace(
        allow_graph=True,
        effective_structured_allowed_entity_types=frozenset({"person"}),
        effective_structured_allowed_predicates=PREDICATE_REGISTRY,
    )
    policy = SimpleNamespace(allow_graph_write=True, graph_scope="full")

    prepared, _rejected = pipeline._build_structured_graph_candidates(
        event=event,
        profile=profile,
        policy=policy,
        evidence_event_ids=["evt-sgh"],
        catalog_name_index=None,
        classification=classification,
    )

    assert len(prepared) == 1
    assert prepared[0]["evidence_class"] == EvidenceClass.USER_SELF_REPORT.label
