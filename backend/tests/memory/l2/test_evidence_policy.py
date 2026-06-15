from __future__ import annotations

from magi.memory.evidence import EvidenceClassification, L1RetrievalScope, resolve_l2_policy


def _classification(evidence_class: str) -> EvidenceClassification:
    return EvidenceClassification(
        evidence_class=evidence_class,
        reason_code="test",
        speaker_role="user",
        grounding_type="self_reported",
        semantic_owner="user",
        originality_type="primary",
        source_event_ids=[],
    )


def test_policy_allows_full_writes_for_user_self_report():
    decision = resolve_l2_policy(_classification("user_self_report"))

    assert decision.allow_entity_extraction is True
    assert decision.allow_graph_write is True
    assert decision.allow_assertion_write is True
    assert decision.allow_snapshot_impact is True
    assert decision.l1_retrieval_scope == "fact_authoritative"
    assert decision.graph_scope == "full"
    assert decision.assertion_scope == "full"
    assert decision.evidence_weight == 1.0
    assert decision.count_as_new_evidence is True
    assert decision.require_source_backlink is False
    assert decision.skip_reason is None


def test_policy_limits_user_report_about_others():
    decision = resolve_l2_policy(_classification("user_report_about_others"))

    assert decision.allow_entity_extraction is True
    assert decision.allow_graph_write is True
    assert decision.allow_assertion_write is True
    assert decision.allow_snapshot_impact is False
    assert decision.l1_retrieval_scope == "fact_authoritative"
    assert decision.graph_scope == "full"
    assert decision.assertion_scope == "topology_only"
    assert decision.evidence_weight == 0.8
    assert decision.count_as_new_evidence is True


def test_policy_blocks_new_evidence_for_assistant_quote():
    decision = resolve_l2_policy(_classification("assistant_quote"))

    assert decision.allow_entity_extraction is True
    assert decision.allow_graph_write is False
    assert decision.allow_assertion_write is False
    assert decision.allow_snapshot_impact is False
    assert decision.l1_retrieval_scope == "source_backlink_only"
    assert L1RetrievalScope.from_value(decision.l1_retrieval_scope) == L1RetrievalScope.SOURCE_BACKLINK_ONLY
    assert decision.graph_scope == "none"
    assert decision.assertion_scope == "none"
    assert decision.evidence_weight == 0.0
    assert decision.count_as_new_evidence is False
    assert decision.require_source_backlink is True
    assert decision.skip_reason == "assistant_quote"


def test_policy_skips_assistant_tool_grounded():
    decision = resolve_l2_policy(_classification("assistant_tool_grounded"))

    assert decision.allow_entity_extraction is False
    assert decision.allow_graph_write is False
    assert decision.allow_assertion_write is False
    assert decision.allow_snapshot_impact is False
    assert decision.l1_retrieval_scope == "conversation_only"
    assert decision.graph_scope == "none"
    assert decision.assertion_scope == "none"
    assert decision.evidence_weight == 0.0
    assert decision.count_as_new_evidence is False
    assert decision.skip_reason == "assistant_tool_grounded"


def test_policy_skips_assistant_freeform():
    decision = resolve_l2_policy(_classification("assistant_freeform"))

    assert decision.allow_entity_extraction is False
    assert decision.allow_graph_write is False
    assert decision.allow_assertion_write is False
    assert decision.allow_snapshot_impact is False
    assert decision.l1_retrieval_scope == "conversation_only"
    assert decision.evidence_weight == 0.0
    assert decision.skip_reason == "assistant_freeform"


def test_policy_allows_interest_scope_for_external_observation():
    decision = resolve_l2_policy(_classification("external_observation"))

    assert decision.allow_entity_extraction is True
    assert decision.allow_graph_write is True
    assert decision.allow_assertion_write is True
    assert decision.allow_snapshot_impact is False
    assert decision.l1_retrieval_scope == "fact_authoritative"
    assert decision.graph_scope == "full"
    assert decision.assertion_scope == "interest"
    assert decision.evidence_weight == 0.7


def test_policy_skips_system_runtime():
    decision = resolve_l2_policy(_classification("system_runtime"))

    assert decision.allow_entity_extraction is False
    assert decision.allow_graph_write is False
    assert decision.allow_assertion_write is False
    assert decision.allow_snapshot_impact is False
    assert decision.l1_retrieval_scope == "audit_only"
    assert decision.count_as_new_evidence is False
    assert decision.skip_reason == "system_runtime"


def test_policy_rejects_unknown_evidence_class():
    try:
        resolve_l2_policy(_classification("mystery_class"))
    except ValueError as exc:
        assert "Unsupported evidence_class" in str(exc)
    else:
        raise AssertionError("resolve_l2_policy should reject unknown evidence classes")
