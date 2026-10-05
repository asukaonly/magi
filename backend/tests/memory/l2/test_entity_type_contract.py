"""Cross-boundary entity type and request-local evidence contracts."""

from magi.memory.l2.models import L2BatchEvent, L2EventWindow
from magi.memory.l2.pipeline.prompts import render_phase1_extract_prompt
from magi.memory.l2.prompt_evidence_refs import evidence_ref_labels, restore_evidence_refs


def test_model_instructions_separate_extractable_types_from_source_owned_states():
    from magi.memory.l2.entity_types import render_entity_type_instructions

    from magi.memory.l2.pipeline.prompts import PHASE1_EXTRACT_SYSTEM_PROMPT

    instructions = render_entity_type_instructions()
    assert instructions in PHASE1_EXTRACT_SYSTEM_PROMPT
    extractable, structured = instructions.split("### Structured source types")
    assert all(f"`{kind}`" in extractable for kind in ("brand", "service", "group"))
    assert "`presence`" not in extractable
    assert "`presence`" in structured


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
