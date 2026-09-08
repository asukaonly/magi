"""Cross-boundary entity type and request-local evidence contracts."""

from magi.memory.l2.entity_types import ENTITY_TYPES, EXTRACTABLE_ENTITY_TYPES
from magi.memory.l2.models import L2BatchEvent, L2EventWindow
from magi.memory.l2.ontology import normalize_entity_type
from magi.memory.l2.pipeline.prompts import render_phase1_extract_prompt
from magi.memory.l2.prompt_evidence_refs import evidence_ref_labels, restore_evidence_refs


def test_categories_distinguish_brands_services_and_source_states():
    assert normalize_entity_type("service") == "service"
    assert normalize_entity_type("application") == "software"
    assert {"brand", "service", "group"} <= EXTRACTABLE_ENTITY_TYPES
    assert "presence" not in EXTRACTABLE_ENTITY_TYPES
    assert len({item.key for item in ENTITY_TYPES}) == len(ENTITY_TYPES)
    assert all(item.label_en and item.label_zh and item.boundary for item in ENTITY_TYPES)


def test_evidence_labels_do_not_rewrite_quotes_or_cross_request_identity():
    window = L2EventWindow(events=[L2BatchEvent(event_id="durable-uuid", content="I like E1.", author_type="user")])
    labels = evidence_ref_labels(window, [{"event_id": "prior-uuid", "content": "What do you like?"}])
    prompt = render_phase1_extract_prompt(event_window=window, focal_subject={}, event_ref_labels=labels)
    assert "[USER] [#E1]" in prompt
    assert "durable-uuid" not in prompt
    assert "I like E1." in prompt
    payload = {"fact_claims": [{"supporting_event_ids": ["#E1"], "antecedent_event_ids": ["C1"], "evidence_text": "I like E1."}]}
    restore_evidence_refs(payload, labels)
    claim = payload["fact_claims"][0]
    assert claim["supporting_event_ids"] == ["durable-uuid"]
    assert claim["antecedent_event_ids"] == ["prior-uuid"]
    assert claim["evidence_text"] == "I like E1."
