"""Ontology admission and retrieval grouping contracts."""

import pytest
from magi.memory.l2.ontology import (
    are_predicates_synonymous,
    coerce_unknown_entity_type,
    expand_predicate_group,
    get_predicate_synonym_group,
    is_valid_entity_type,
    is_valid_open_predicate,
    normalize_entity_type,
    predicates_for_family,
    validate_assertion_candidate,
    validate_graph_candidate,
)
from magi.memory.l2.ontology_aliases import canonicalize_predicate


@pytest.mark.parametrize(
    "value,normalized,valid,coerced",
    [
        ("service", "service", True, "service"),
        ("application", "software", True, "software"),
        ("dish", "food", True, "food"),
        (" Food ", "food", True, "food"),
        ("mystery_type", "mystery_type", False, "other"),
        ("none", "none", False, "other"),
        (None, None, False, "other"),
        ("  ", None, False, "other"),
    ],
)
def test_entity_type_normalization_and_unknown_admission(value, normalized, valid, coerced):
    assert normalize_entity_type(value) == normalized
    assert is_valid_entity_type(value) is valid
    assert coerce_unknown_entity_type(value) == coerced


@pytest.mark.parametrize(
    "predicate,object_type,reference,reason",
    [
        ("DISLIKES", "food", "tea", None),
        ("DISLIKES", "health_metric", "weight", None),
        ("HAS_METRIC", "health_metric", "weight", None),
        ("HAS_METRIC", "food", "tea", "invalid_object_type"),
        ("LIVES_IN", "place", "Kyoto", None),
        ("LIVES_IN", "organization", "OpenAI", "invalid_object_type"),
        ("VISITED", "virtual_object", "website", None),
        ("ON_PLATFORM", "food", "tea", "invalid_object_type"),
        ("adores food", "food", "tea", "invalid_predicate"),
        ("ALLERGIC_TO", "food", "tea", None),
        ("learning", "software", "Python", None),
        ("ASKED_ABOUT", "software", "GitHub", "low_value_predicate"),
        ("mentioned", "software", "GitHub", "low_value_predicate"),
        ("MAINTAINS", "software", "GitHub", None),
        ("MAINTAINS", "software", "那个", "vague_entity_reference"),
        ("KNOWS", "person", "person:他", "vague_entity_reference"),
        ("MAINTAINS", "software", "software:app", "vague_entity_reference"),
        ("KNOWS", "person", "person:德克萨斯", None),
        ("PREFERENCE_PROFILE", "concept", "子涵", "reserved_assertion_predicate"),
        ("PREFERRED_FORM_OF_ADDRESS", "concept", "子涵", "profile_signal_predicate"),
        ("LIKES", "concept", "preference.address.preferred", "reserved_assertion_identifier"),
        (
            "LIKES",
            "concept",
            "concept:preference-address-preferred",
            "reserved_assertion_identifier",
        ),
        ("LIKES", "concept", "stress.level.current", "reserved_assertion_identifier"),
        ("LIKES", "concept", "preference_profile", "reserved_assertion_identifier"),
        ("LIKES", "concept", "concept:mood-board", None),
        ("LIKES", "concept", "concept:mood-board-blue", None),
    ],
)
def test_graph_admission_enforces_predicate_type_and_reference_boundaries(
    predicate, object_type, reference, reason
):
    assert validate_graph_candidate(
        {"predicate": predicate, "object_type": object_type, "object_ref": reference}
    ) == (reason is None, reason)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("PREFERRED_ADDRESS", "PREFERRED_FORM_OF_ADDRESS"),
        ("call me", "PREFERRED_FORM_OF_ADDRESS"),
        ("name", "REAL_NAME"),
    ],
)
def test_profile_signal_aliases_keep_canonical_ownership(value, expected):
    assert canonicalize_predicate(value) == expected


@pytest.mark.parametrize("family", ["personality_core", "taste_profile"])
def test_assertion_admission_rejects_unsupported_families(family):
    assert validate_assertion_candidate({"trait_family": family}) == (False, "invalid_trait_family")


@pytest.mark.parametrize(
    "left,right,group,related",
    [
        ("LIKES", "INTERESTED_IN", "affinity", True),
        ("USES", "WORKS_WITH", "usage", True),
        ("VISITED", "ATTENDED", "visit", True),
        ("LIKES", "DISLIKES", "affinity", False),
        ("USES", "LIKES", "usage", False),
        ("HAS_METRIC", "LIKES", None, False),
        ("CREATES", "OWNS", None, False),
        ("DISLIKES", "LIKES", "aversion", False),
    ],
)
def test_predicate_groups_expand_related_relations_without_conflating_opposites(
    left, right, group, related
):
    assert get_predicate_synonym_group(left) == group
    assert are_predicates_synonymous(left, right) is related
    assert (right in expand_predicate_group([left])) is related


@pytest.mark.parametrize(
    "predicate,valid",
    [
        ("LEARNING", True),
        ("ALLERGIC_TO", True),
        ("HAS_2_CATS", True),
        ("learning", False),
        ("foo bar", False),
        ("", False),
        ("_LEADING", False),
    ],
)
def test_open_predicate_syntax(predicate, valid):
    assert is_valid_open_predicate(predicate) is valid


@pytest.mark.parametrize(
    "family,expected",
    [
        ("preference", {"LIKES", "DISLIKES", "INTERESTED_IN", "FOLLOWS"}),
        ("relationship", {"KNOWS", "FAMILY_OF", "INTERACTED_WITH", "MEMBER_OF", "WORKS_AT"}),
        (
            "activity",
            {
                "VISITED",
                "ATTENDED",
                "VIEWED",
                "LISTENED",
                "USES",
                "USED",
                "EXECUTED",
                "WORKS_WITH",
                "COMMITTED",
                "CHECKED_OUT",
                "MERGED",
                "REBASED",
            },
        ),
        ("profile_fact", {"LIVES_IN", "WORKS_AT", "MEMBER_OF", "OWNS", "PROFICIENT_IN"}),
        ("nonexistent", None),
    ],
)
def test_retrieval_family_expands_exact_relation_set(family, expected):
    predicates = predicates_for_family(family)
    assert (None if predicates is None else set(predicates)) == expected


def test_expansion_preserves_ungrouped_predicates_and_removes_duplicates():
    assert expand_predicate_group(["LIKES", "CREATES", "LIKES"]) == [
        "CREATES",
        "INTERESTED_IN",
        "LIKES",
    ]
