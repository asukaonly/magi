"""Host wording states provenance and never turns behavior into a declared preference."""

from magi.memory.l2.factual_rendering import render_behavior_observation
from magi.user_profile.portrait_projection_builder import _item_from_assertion


def test_behavior_wording_is_localized_and_qualified():
    assert render_behavior_observation("爵士乐", recent=True, language="zh-CN") == "根据近期活动推测，你可能关注「爵士乐」。"
    english = render_behavior_observation("jazz", recent=False, language="en")
    assert "repeated activity suggests" in english
    assert "likes" not in english


def test_portrait_retains_provenance_and_real_evidence_refs():
    item = _item_from_assertion({"assertion_id": "a", "trait_name": "interest.jazz", "trait_family": "interest_profile", "trait_value": "爵士乐", "natural_summary": "Recurring interested_in signal for jazz", "inference_depth": "topology_only", "evidence_events": ["source1", "source2"], "memory_subdomain": "state"})
    assert item["evidence_basis"] == "inferred"
    assert item["expression"] == {"kind": "behavior", "value": "爵士乐", "horizon": "recent"}
    assert {"event:source1", "event:source2"}.issubset(item["basis_refs"])
    assert "Recurring" not in item["text"]
