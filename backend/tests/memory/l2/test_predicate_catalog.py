"""Tests for the unified predicate catalog."""

import pytest

from magi.memory.l2.predicate_catalog import (
    ALL_SPECS,
    SPEC_BY_CANONICAL,
    expand_predicates_via_catalog,
    get_answer_kinds,
    get_compatible_object_types,
    get_family_predicates,
    get_natural_label,
    get_spec,
    resolve_predicate,
)


class TestPredicateSpec:

    def test_canonical_index_complete(self):
        for spec in ALL_SPECS:
            assert spec.canonical in SPEC_BY_CANONICAL


class TestGetSpec:
    def test_canonical_lookup(self):
        spec = get_spec("LIKES")
        assert spec is not None
        assert spec.canonical == "LIKES"

    @pytest.mark.parametrize(
        "predicate_input",
        [pytest.param("LIKE", id="alias_lookup"), pytest.param("likes", id="case_insensitive")],
    )
    def test_get_spec_resolves_aliases_and_case(self, predicate_input):
        spec = get_spec(predicate_input)
        assert spec is not None
        assert spec.canonical == "LIKES"


    def test_unknown_returns_none(self):
        assert get_spec("UNKNOWN_PREDICATE") is None


class TestResolve:
    @pytest.mark.parametrize(
        "case_input_predicate,case_expected_predicate",
        [
            pytest.param("LIKES", "LIKES", id="resolve_canonical"),
            pytest.param("VIEWED", "WATCHED", id="resolve_alias"),
        ],
    )
    def test_resolve_canonicalizes_supported_predicate_names(
        self, case_input_predicate, case_expected_predicate
    ):
        assert resolve_predicate(case_expected_predicate) == case_input_predicate


    def test_resolve_unknown(self):
        assert resolve_predicate("FOOBAR") is None


class TestFamilyLookup:
    def test_preference_family(self):
        preds = get_family_predicates("preference")
        assert "LIKES" in preds
        assert "DISLIKES" in preds

    def test_empty_family(self):
        assert get_family_predicates("nonexistent") == []


class TestSynonymExpansion:
    def test_expand_affinity(self):
        expanded = expand_predicates_via_catalog(["LIKES"])
        assert "INTERESTED_IN" in expanded

    def test_expand_unknown_passthrough(self):
        expanded = expand_predicates_via_catalog(["CUSTOM_PRED"])
        assert "CUSTOM_PRED" in expanded


class TestNaturalLabel:
    @pytest.mark.parametrize(
        "case_language,case_expected_label",
        [pytest.param("en", "likes", id="english"), pytest.param("zh", "喜欢", id="chinese")],
    )
    def test_predicate_label_uses_requested_language(self, case_language, case_expected_label):
        label = get_natural_label("LIKES", case_language)
        assert label == case_expected_label


    def test_unknown(self):
        assert get_natural_label("FOOBAR") is None


class TestCompatibility:
    def test_has_metric_restricted(self):
        types = get_compatible_object_types("HAS_METRIC")
        assert types is not None
        assert "health_metric" in types

    def test_likes_unrestricted(self):
        types = get_compatible_object_types("LIKES")
        assert types is None


class TestAnswerKinds:
    def test_likes_answer_kinds(self):
        kinds = get_answer_kinds("LIKES")
        assert "creator" in kinds
        assert "place" in kinds
