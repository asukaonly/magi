"""Host wording states provenance and never turns behavior into a declared preference."""

from magi.user_profile.portrait_projection_builder import _item_from_assertion


def test_portrait_retains_provenance_and_real_evidence_refs():
    item = _item_from_assertion({
        "assertion_id": "a", "entity_id": "user:local_user", "entity_type": "user",
        "trait_name": "interest.attention", "trait_family": "interest_profile",
        "trait_value": "interested", "target_entity_id": "topic:jazz",
        "target_entity_name": "爵士乐", "temporal_scope": "recent",
        "natural_summary": "Recurring interested_in signal for jazz",
        "inference_depth": "topology_only", "evidence_events": ["source1", "source2"],
        "memory_subdomain": "state",
    })
    assert item["evidence_basis"] == "inferred"
    assert item["expression"] == {"kind": "behavior", "value": "爵士乐", "horizon": "recent"}
    assert {"event:source1", "event:source2"}.issubset(item["basis_refs"])
    assert "Recurring" not in item["text"]
