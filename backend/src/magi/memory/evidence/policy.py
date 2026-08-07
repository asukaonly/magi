"""Rule-based memory evidence policy resolution."""

from __future__ import annotations

from .models import (
    EvidenceClass,
    EvidenceClassification,
    GraphScope,
    L1RetrievalScope,
    PolicyDecision,
)


def event_allows_l2_projection(event) -> bool:
    """Return whether the shared evidence policy permits an L2 write."""
    from .classifier import classify_event_evidence

    policy = resolve_l2_policy(classify_event_evidence(event))
    return policy_allows_l2_projection(policy)


def policy_allows_l2_projection(policy: PolicyDecision) -> bool:
    """Return whether a resolved policy requires durable L2 projection."""
    return bool(policy.allow_graph_write or policy.allow_assertion_write)


def resolve_l2_policy(classification: EvidenceClassification) -> PolicyDecision:
    """Map an evidence class to a deterministic L2 write policy."""

    try:
        evidence_class = EvidenceClass.from_value(classification.evidence_class)
    except ValueError as exc:
        raise ValueError(f"Unsupported evidence_class: {classification.evidence_class}") from exc
    try:
        return _POLICY_MATRIX[evidence_class]
    except KeyError as exc:
        raise ValueError(f"Unsupported evidence_class: {classification.evidence_class}") from exc


_POLICY_MATRIX: dict[EvidenceClass, PolicyDecision] = {
    EvidenceClass.USER_SELF_REPORT: PolicyDecision(
        allow_entity_extraction=True,
        allow_graph_write=True,
        allow_assertion_write=True,
        allow_snapshot_impact=True,
        l1_retrieval_scope=L1RetrievalScope.FACT_AUTHORITATIVE.label,
        graph_scope=GraphScope.FULL.label,
        evidence_weight=1.0,
        count_as_new_evidence=True,
        require_source_backlink=False,
    ),
    EvidenceClass.ASSISTANT_QUOTE: PolicyDecision(
        allow_entity_extraction=True,
        allow_graph_write=False,
        allow_assertion_write=False,
        allow_snapshot_impact=False,
        l1_retrieval_scope="source_backlink_only",
        graph_scope=GraphScope.NONE.label,
        evidence_weight=0.0,
        count_as_new_evidence=False,
        require_source_backlink=True,
        skip_reason="assistant_quote",
    ),
    EvidenceClass.ASSISTANT_TOOL_GROUNDED: PolicyDecision(
        allow_entity_extraction=False,
        allow_graph_write=False,
        allow_assertion_write=False,
        allow_snapshot_impact=False,
        l1_retrieval_scope=L1RetrievalScope.CONVERSATION_ONLY.label,
        graph_scope=GraphScope.NONE.label,
        evidence_weight=0.0,
        count_as_new_evidence=False,
        require_source_backlink=False,
        skip_reason="assistant_tool_grounded",
    ),
    EvidenceClass.ASSISTANT_FREEFORM: PolicyDecision(
        allow_entity_extraction=False,
        allow_graph_write=False,
        allow_assertion_write=False,
        allow_snapshot_impact=False,
        l1_retrieval_scope=L1RetrievalScope.CONVERSATION_ONLY.label,
        graph_scope=GraphScope.NONE.label,
        evidence_weight=0.0,
        count_as_new_evidence=False,
        require_source_backlink=False,
        skip_reason="assistant_freeform",
    ),
    EvidenceClass.ASSISTANT_RUNTIME_DERIVATION: PolicyDecision(
        allow_entity_extraction=False,
        allow_graph_write=False,
        allow_assertion_write=False,
        allow_snapshot_impact=False,
        l1_retrieval_scope=L1RetrievalScope.CONVERSATION_ONLY.label,
        graph_scope=GraphScope.NONE.label,
        evidence_weight=0.0,
        count_as_new_evidence=False,
        require_source_backlink=False,
        skip_reason="assistant_runtime_derivation",
    ),
    EvidenceClass.EXTERNAL_OBSERVATION: PolicyDecision(
        allow_entity_extraction=True,
        allow_graph_write=True,
        allow_assertion_write=False,
        allow_snapshot_impact=False,
        l1_retrieval_scope=L1RetrievalScope.FACT_AUTHORITATIVE.label,
        graph_scope=GraphScope.FULL.label,
        evidence_weight=0.7,
        count_as_new_evidence=True,
        require_source_backlink=False,
    ),
    EvidenceClass.SYSTEM_RUNTIME: PolicyDecision(
        allow_entity_extraction=False,
        allow_graph_write=False,
        allow_assertion_write=False,
        allow_snapshot_impact=False,
        l1_retrieval_scope=L1RetrievalScope.AUDIT_ONLY.label,
        graph_scope=GraphScope.NONE.label,
        evidence_weight=0.0,
        count_as_new_evidence=False,
        require_source_backlink=False,
        skip_reason="system_runtime",
    ),
    EvidenceClass.USER_QUESTION: PolicyDecision(
        # Asking is a conversation act, not new user-profile evidence. The
        # event is still retrievable as conversation context but never feeds
        # graph/assertion writes and is not authoritative for fact recall.
        allow_entity_extraction=False,
        allow_graph_write=False,
        allow_assertion_write=False,
        allow_snapshot_impact=False,
        l1_retrieval_scope=L1RetrievalScope.CONVERSATION_ONLY.label,
        graph_scope=GraphScope.NONE.label,
        evidence_weight=0.0,
        count_as_new_evidence=False,
        require_source_backlink=False,
        skip_reason="user_question",
    ),
    EvidenceClass.USER_REQUEST: PolicyDecision(
        # Imperatives describe what the user wants done now; they are not
        # durable self-reports about the user themselves. Treat them as
        # conversation-only context for the same reasons as USER_QUESTION.
        allow_entity_extraction=False,
        allow_graph_write=False,
        allow_assertion_write=False,
        allow_snapshot_impact=False,
        l1_retrieval_scope=L1RetrievalScope.CONVERSATION_ONLY.label,
        graph_scope=GraphScope.NONE.label,
        evidence_weight=0.0,
        count_as_new_evidence=False,
        require_source_backlink=False,
        skip_reason="user_request",
    ),
}


__all__ = [
    "PolicyDecision",
    "event_allows_l2_projection",
    "policy_allows_l2_projection",
    "resolve_l2_policy",
]
