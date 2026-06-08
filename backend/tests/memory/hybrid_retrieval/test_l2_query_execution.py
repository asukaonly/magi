"""Tests for the L2 query execution trace dict."""

from magi.memory.evidence import EvidenceClass
from magi.memory.hybrid_retrieval.grounding import L2GroundingPlan
from magi.memory.hybrid_retrieval.l2_query_execution import (
    _build_grounding_plan_trace,
)


def test_grounding_plan_trace_includes_evidence_classes():
    """The trace dict should include allowed_evidence_classes as a sorted list."""
    plan = L2GroundingPlan()
    plan.allowed_evidence_classes = {
        EvidenceClass.USER_SELF_REPORT.label,
        EvidenceClass.EXTERNAL_OBSERVATION.label,
    }

    trace = _build_grounding_plan_trace(plan)

    assert "allowed_evidence_classes" in trace
    assert trace["allowed_evidence_classes"] == sorted(
        {
            EvidenceClass.USER_SELF_REPORT.label,
            EvidenceClass.EXTERNAL_OBSERVATION.label,
        }
    )
    # sorted() on strings is lexicographic; pin the expected ordering so
    # operators reading the log see a stable shape.
    assert trace["allowed_evidence_classes"] == [
        "external_observation",
        "user_self_report",
    ]


def test_grounding_plan_trace_evidence_classes_none_when_unset():
    """When the plan has no evidence-class filter, the trace key is None."""
    plan = L2GroundingPlan()
    assert plan.allowed_evidence_classes is None

    trace = _build_grounding_plan_trace(plan)

    assert trace["allowed_evidence_classes"] is None


def test_grounding_plan_trace_evidence_classes_none_when_empty():
    """An empty set is treated the same as None (no narrowing applied)."""
    plan = L2GroundingPlan()
    plan.allowed_evidence_classes = set()

    trace = _build_grounding_plan_trace(plan)

    assert trace["allowed_evidence_classes"] is None


def test_grounding_plan_trace_preserves_existing_keys():
    """Existing trace keys must keep their shape — log consumers grep them."""
    plan = L2GroundingPlan()

    trace = _build_grounding_plan_trace(plan)

    expected_keys = {
        "query_kind",
        "subject_scope",
        "answer_kind",
        "predicate_family",
        "confidence",
        "temporal_mode",
        "subject_count",
        "object_count",
        "predicate_count",
        "allowed_evidence_classes",
        "evidence_focus_source",
        "predicate_source",
    }
    assert set(trace.keys()) == expected_keys
    assert trace["query_kind"] == "unknown"
    assert trace["subject_scope"] == "none"
    assert trace["answer_kind"] == "unknown"
    assert trace["predicate_family"] is None
    assert trace["confidence"] == 0.5
    assert trace["subject_count"] == 0
    assert trace["object_count"] == 0
    assert trace["predicate_count"] == 0


def test_grounding_plan_trace_includes_evidence_focus_source():
    """Trace must report which path set allowed_evidence_classes — useful for
    measuring how often the family fallback is triggered (Phase 2A spec 4.7)."""
    from magi.memory.hybrid_retrieval.grounding import L2GroundingPlan
    from magi.memory.hybrid_retrieval.l2_query_execution import (
        _build_grounding_plan_trace,
    )

    plan = L2GroundingPlan()
    plan.allowed_evidence_classes = {"user_self_report"}
    plan.evidence_focus_source = "llm"
    trace = _build_grounding_plan_trace(plan)
    assert trace["evidence_focus_source"] == "llm"


def test_grounding_plan_trace_evidence_focus_source_none_when_unset():
    from magi.memory.hybrid_retrieval.grounding import L2GroundingPlan
    from magi.memory.hybrid_retrieval.l2_query_execution import (
        _build_grounding_plan_trace,
    )

    plan = L2GroundingPlan()
    trace = _build_grounding_plan_trace(plan)
    assert trace["evidence_focus_source"] is None


def test_grounding_plan_trace_includes_predicate_source():
    """Trace must report which resolver path produced the predicates (RFC #65 P1)."""
    plan = L2GroundingPlan()
    plan.predicate_source = "embedding"
    trace = _build_grounding_plan_trace(plan)
    assert trace["predicate_source"] == "embedding"


def test_grounding_plan_trace_predicate_source_none_when_unset():
    """When no resolver has run, predicate_source is None in the trace."""
    plan = L2GroundingPlan()
    trace = _build_grounding_plan_trace(plan)
    assert trace["predicate_source"] is None
