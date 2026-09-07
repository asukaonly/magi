"""Extraction admission and Claim authority must not upgrade whole events."""

from dataclasses import replace

import pytest

from magi.memory.evidence import (
    classify_event_evidence,
    resolve_l2_policy,
    resolve_l2_extraction_policy,
)
from magi.memory.l2.phase1_models import L2Phase1FactClaim
from magi.memory.l2.pipeline.claim_evidence import (
    grounded_claim_evidence_class,
    resolve_claim_graph_sources,
)
from .test_pipeline import _make_memory_event


@pytest.mark.parametrize("text", ["请叫我小明", "你觉得哪种电脑好？"])
def test_extraction_admission_keeps_event_fact_authority_closed(text):
    event = _make_memory_event(event_id="evt-request", content=text)
    classification = classify_event_evidence(event)
    policy = resolve_l2_extraction_policy(classification)
    assert policy.allow_entity_extraction
    assert not policy.allow_assertion_write
    assert not policy.allow_graph_write
    assert policy.l1_retrieval_scope == "conversation_only"
    assert not resolve_l2_policy(classification).allow_entity_extraction


def test_only_an_asserted_claim_can_gain_authority_from_user_request():
    event = _make_memory_event(event_id="evt-request", content="请叫我小明")
    classification = classify_event_evidence(event)
    asserted = L2Phase1FactClaim(evidence_text=event.content)
    assert grounded_claim_evidence_class(asserted, classification) == "user_self_report"
    assert grounded_claim_evidence_class(replace(asserted, assertion_mode="request"), classification) == "user_request"
    assert classification.evidence_class == "user_request"


def test_graph_source_comes_from_claim_support_in_any_batch_order():
    event = _make_memory_event(event_id="evt-support", content="请叫我小明")
    unrelated = replace(event, event_id="evt-unrelated", timestamp=event.timestamp + 100, source="another-source")
    claim = L2Phase1FactClaim(claim_id="clm-1", supporting_event_ids=[event.event_id])
    evidence = [
        (item, classification := classify_event_evidence(item), resolve_l2_extraction_policy(classification))
        for item in [event, unrelated]
    ]
    for batch in [evidence, list(reversed(evidence))]:
        source = resolve_claim_graph_sources([claim], batch)[claim.claim_id]
        assert source.event.event_id == "evt-support"
        assert source.event.timestamp == event.timestamp
        assert source.evidence_class == "user_self_report"
