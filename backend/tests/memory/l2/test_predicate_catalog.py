"""Catalog alias integrity and consumer lookup contracts."""

import pytest
from magi.memory.l2.predicate_catalog import (
    ALL_SPECS,
    SPEC_BY_CANONICAL,
    expand_predicates_via_catalog,
    get_family_predicates,
    get_natural_label,
    get_spec,
    resolve_predicate,
)


def test_catalog_indexes_preserve_unique_canonical_and_alias_identity():
    assert len(SPEC_BY_CANONICAL) == len(ALL_SPECS)
    assert set(SPEC_BY_CANONICAL) == {spec.canonical for spec in ALL_SPECS}
    for spec in ALL_SPECS:
        assert SPEC_BY_CANONICAL[spec.canonical] is spec
        for alias in (spec.canonical, *spec.aliases):
            assert get_spec(alias) is spec
            assert resolve_predicate(alias) == spec.canonical


@pytest.mark.parametrize(
    "value,expected",
    [
        ("LIKES", "LIKES"),
        ("LIKE", "LIKES"),
        (" likes ", "LIKES"),
        ("WATCHED", "VIEWED"),
        ("FOOBAR", None),
    ],
)
def test_catalog_lookup_normalizes_names_and_rejects_unknowns(value, expected):
    spec = get_spec(value)
    assert (None if spec is None else spec.canonical) == expected
    assert resolve_predicate(value) == expected


@pytest.mark.parametrize(
    "family,expected",
    [
        ("preference", {"LIKES", "DISLIKES", "INTERESTED_IN", "FOLLOWS"}),
        ("nonexistent", set()),
    ],
)
def test_catalog_family_lookup_excludes_other_families(family, expected):
    assert set(get_family_predicates(family)) == expected


@pytest.mark.parametrize(
    "predicates,expected",
    [
        (["LIKE", "LIKES"], ["INTERESTED_IN", "LIKES"]),
        (["CUSTOM_PRED"], ["CUSTOM_PRED"]),
        (["LIKE", "CUSTOM_PRED"], ["CUSTOM_PRED", "INTERESTED_IN", "LIKES"]),
    ],
)
def test_catalog_expansion_canonicalizes_and_preserves_open_predicates(predicates, expected):
    assert expand_predicates_via_catalog(predicates) == expected


@pytest.mark.parametrize(
    "predicate,language,expected",
    [
        ("LIKES", "en", "likes"),
        ("LIKES", "zh", "喜欢"),
        ("FOOBAR", "en", None),
    ],
)
def test_catalog_labels_follow_language_and_unknown_contract(predicate, language, expected):
    assert get_natural_label(predicate, language) == expected
