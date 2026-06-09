"""Tests for the REFERENCES predicate (issue #55).

REFERENCES lets source-declared reference edges (e.g. an Obsidian wikilink,
a commit referencing an issue, a chat referencing a doc) land in the L2
knowledge graph deterministically, without LLM inference. It must be a
first-class registry predicate, in its own family/synonym group so recall
expansion does not pull in unrelated predicates.
"""

from magi.memory.l2.ontology import (
    PREDICATE_REGISTRY,
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


def test_references_in_predicate_registry():
    assert "REFERENCES" in PREDICATE_REGISTRY


def test_references_not_low_value():
    # REFERENCED (past tense) is blacklisted as low-value; REFERENCES must NOT be.
    assert is_low_value_open_predicate("REFERENCES") is False


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


def test_references_has_its_own_family():
    assert "REFERENCES" in get_family_predicates("reference")
    assert "REFERENCES" in (predicates_for_family("reference") or [])


def test_references_expansion_does_not_pollute():
    # Expanding REFERENCES must not pull in unrelated predicates (e.g. activity siblings
    # like COMMITTED/VISITED). It is alone in its synonym group.
    assert expand_predicates_via_catalog(["REFERENCES"]) == ["REFERENCES"]


def test_references_catalog_spec():
    spec = get_spec("REFERENCES")
    assert spec is not None
    assert spec.canonical == "REFERENCES"
    assert spec.family == "reference"
    assert get_natural_label("REFERENCES", "en")
