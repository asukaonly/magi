"""Tests for the unified predicate catalog."""

import pytest

from magi.memory.l2.predicate_catalog import (
    ALL_SPECS,
    SPEC_BY_CANONICAL,
    SPEC_BY_ALIAS,
    SPECS_BY_FAMILY,
    PredicateSpec,
    expand_predicates_via_catalog,
    get_answer_kinds,
    get_compatible_object_types,
    get_family_predicates,
    get_natural_label,
    get_spec,
    get_synonym_group_predicates,
    resolve_predicate,
)


class TestPredicateSpec:
    def test_all_specs_populated(self):
        assert len(ALL_SPECS) > 20

    def test_canonical_index_complete(self):
        for spec in ALL_SPECS:
            assert spec.canonical in SPEC_BY_CANONICAL

    def test_alias_index_no_overlap_with_canonical(self):
        for alias, spec in SPEC_BY_ALIAS.items():
            assert alias != spec.canonical or alias in SPEC_BY_CANONICAL


class TestGetSpec:
    def test_canonical_lookup(self):
        spec = get_spec("LIKES")
        assert spec is not None
        assert spec.canonical == "LIKES"

    def test_alias_lookup(self):
        spec = get_spec("LIKE")
        assert spec is not None
        assert spec.canonical == "LIKES"

    def test_case_insensitive(self):
        spec = get_spec("likes")
        assert spec is not None
        assert spec.canonical == "LIKES"

    def test_unknown_returns_none(self):
        assert get_spec("UNKNOWN_PREDICATE") is None


class TestResolve:
    def test_resolve_canonical(self):
        assert resolve_predicate("LIKES") == "LIKES"

    def test_resolve_alias(self):
        assert resolve_predicate("WATCHED") == "VIEWED"

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
    def test_english(self):
        label = get_natural_label("LIKES", "en")
        assert label == "likes"

    def test_chinese(self):
        label = get_natural_label("LIKES", "zh")
        assert label == "喜欢"

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
