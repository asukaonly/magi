"""Rule-based L2 write policy resolution."""

from __future__ import annotations

from dataclasses import dataclass

from .l2_evidence_classifier import EvidenceClassification


@dataclass(slots=True)
class PolicyDecision:
    """Resolved write policy for one classified evidence item."""

    allow_entity_extraction: bool
    allow_graph_write: bool
    allow_assertion_write: bool
    allow_snapshot_impact: bool
    graph_scope: str
    assertion_scope: str
    evidence_weight: float
    count_as_new_evidence: bool
    require_source_backlink: bool
    skip_reason: str | None = None


def resolve_l2_policy(classification: EvidenceClassification) -> PolicyDecision:
    """Map an evidence class to a deterministic L2 write policy."""

    evidence_class = classification.evidence_class.strip()
    try:
        return _POLICY_MATRIX[evidence_class]
    except KeyError as exc:
        raise ValueError(f"Unsupported evidence_class: {classification.evidence_class}") from exc


_POLICY_MATRIX: dict[str, PolicyDecision] = {
    "user_self_report": PolicyDecision(
        allow_entity_extraction=True,
        allow_graph_write=True,
        allow_assertion_write=True,
        allow_snapshot_impact=True,
        graph_scope="full",
        assertion_scope="full",
        evidence_weight=1.0,
        count_as_new_evidence=True,
        require_source_backlink=False,
    ),
    "user_report_about_others": PolicyDecision(
        allow_entity_extraction=True,
        allow_graph_write=True,
        allow_assertion_write=True,
        allow_snapshot_impact=False,
        graph_scope="full",
        assertion_scope="topology_only",
        evidence_weight=0.8,
        count_as_new_evidence=True,
        require_source_backlink=False,
    ),
    "assistant_quote": PolicyDecision(
        allow_entity_extraction=True,
        allow_graph_write=False,
        allow_assertion_write=False,
        allow_snapshot_impact=False,
        graph_scope="none",
        assertion_scope="none",
        evidence_weight=0.0,
        count_as_new_evidence=False,
        require_source_backlink=True,
        skip_reason="assistant_quote",
    ),
    "assistant_tool_grounded": PolicyDecision(
        allow_entity_extraction=False,
        allow_graph_write=False,
        allow_assertion_write=False,
        allow_snapshot_impact=False,
        graph_scope="none",
        assertion_scope="none",
        evidence_weight=0.0,
        count_as_new_evidence=False,
        require_source_backlink=False,
        skip_reason="assistant_tool_grounded",
    ),
    "assistant_freeform": PolicyDecision(
        allow_entity_extraction=False,
        allow_graph_write=False,
        allow_assertion_write=False,
        allow_snapshot_impact=False,
        graph_scope="none",
        assertion_scope="none",
        evidence_weight=0.0,
        count_as_new_evidence=False,
        require_source_backlink=False,
        skip_reason="assistant_freeform",
    ),
    "external_observation": PolicyDecision(
        allow_entity_extraction=True,
        allow_graph_write=True,
        allow_assertion_write=True,
        allow_snapshot_impact=False,
        graph_scope="full",
        assertion_scope="topology_only",
        evidence_weight=0.7,
        count_as_new_evidence=True,
        require_source_backlink=False,
    ),
    "system_runtime": PolicyDecision(
        allow_entity_extraction=False,
        allow_graph_write=False,
        allow_assertion_write=False,
        allow_snapshot_impact=False,
        graph_scope="none",
        assertion_scope="none",
        evidence_weight=0.0,
        count_as_new_evidence=False,
        require_source_backlink=False,
        skip_reason="system_runtime",
    ),
}


__all__ = ["PolicyDecision", "resolve_l2_policy"]
