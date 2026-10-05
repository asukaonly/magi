"""Tests for the REFERENCES predicate (issue #55).

REFERENCES lets source-declared reference edges (e.g. an Obsidian wikilink,
a commit referencing an issue, a chat referencing a doc) land in the L2
knowledge graph deterministically, without LLM inference. It must be a
first-class registry predicate, in its own family/synonym group so recall
expansion does not pull in unrelated predicates.
"""

from magi.memory.l2.ontology import (
    is_low_value_open_predicate,
    predicates_for_family,
    validate_graph_candidate,
)
from magi.memory.l2.predicate_catalog import (
    expand_predicates_via_catalog,
    get_family_predicates,
    get_natural_label,
    get_spec,
)


def test_reference_predicate_is_distinct_from_dialogue_reference():
    for predicate, accepted in [("REFERENCES", True), ("REFERENCED", False)]:
        assert is_low_value_open_predicate(predicate) is not accepted
        valid, reason = validate_graph_candidate(
            {
                "predicate": predicate,
                "object_type": "concept",
                "object_ref": "concept:event-sourcing",
            }
        )
        assert valid is accepted
        if not accepted:
            assert reason == "low_value_predicate"


def test_references_validates_for_registry_object_types():
    # A note -> concept reference (an Obsidian wikilink target) must pass.
    ok, reason = validate_graph_candidate(
        {
            "predicate": "REFERENCES",
            "object_type": "concept",
            "object_ref": "concept:event-sourcing",
        }
    )
    assert ok, reason
    # Permissive across registry entity types (a note can reference a person, topic, ...).
    ok_person, _ = validate_graph_candidate(
        {"predicate": "REFERENCES", "object_type": "person", "object_ref": "person:alex"}
    )
    assert ok_person


def test_reference_catalog_keeps_its_family_and_locale_labels():
    assert get_family_predicates("reference") == ["REFERENCES"]
    assert predicates_for_family("reference") == ["REFERENCES"]
    spec = get_spec("REFERENCES")
    assert spec is not None
    assert (spec.canonical, spec.family) == ("REFERENCES", "reference")
    assert get_natural_label("REFERENCES", "en") == "references"
    assert get_natural_label("REFERENCES", "zh") == "引用"


def test_references_expansion_does_not_pollute():
    # Expanding REFERENCES must not pull in unrelated predicates (e.g. activity siblings
    # like COMMITTED/VISITED). It is alone in its synonym group.
    assert expand_predicates_via_catalog(["REFERENCES"]) == ["REFERENCES"]
