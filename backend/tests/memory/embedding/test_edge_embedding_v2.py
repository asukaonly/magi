"""Tests for v2 edge embedding text builder."""

import time

import pytest

from magi.memory.embedding.embedding_text_builders import (
    build_l2_edge_embedding_text,
    build_l2_edge_embedding_text_v2,
)


class TestBuildL2EdgeEmbeddingTextV2:
    def test_basic_output_has_structure(self):
        text = build_l2_edge_embedding_text_v2(
            subject_id="user:alice",
            predicate="LIKES",
            object_id="food:pizza",
            subject_name="Alice",
            object_name="Pizza",
        )
        assert "Subject: Alice" in text
        assert "Relation:" in text
        assert "likes" in text.lower()
        assert "Object: Pizza" in text

    def test_includes_object_type(self):
        text = build_l2_edge_embedding_text_v2(
            subject_id="user:alice",
            predicate="LIKES",
            object_id="food:pizza",
            object_type="food",
        )
        assert "Object type: food" in text

    def test_includes_status(self):
        text = build_l2_edge_embedding_text_v2(
            subject_id="user:alice",
            predicate="LIKES",
            object_id="food:pizza",
            status="active",
        )
        assert "Status: active" in text

    def test_coarse_time_hint_recent(self):
        text = build_l2_edge_embedding_text_v2(
            subject_id="u",
            predicate="LIKES",
            object_id="o",
            first_observed_at=time.time() - 3600,
        )
        assert "recent" in text.lower()

    def test_deduplicates_identical_summary_evidence(self):
        text = build_l2_edge_embedding_text_v2(
            subject_id="u",
            predicate="LIKES",
            object_id="o",
            natural_summary="Alice likes pizza",
            evidence_text="Alice likes pizza",
        )
        count = text.lower().count("alice likes pizza")
        assert count == 1

    def test_deduplicates_contained_summary(self):
        text = build_l2_edge_embedding_text_v2(
            subject_id="u",
            predicate="LIKES",
            object_id="o",
            natural_summary="likes pizza",
            evidence_text="Alice really likes pizza very much",
        )
        assert "Summary:" not in text
        assert "Evidence:" in text

    def test_bounds_evidence_length(self):
        long_evidence = "word " * 200
        text = build_l2_edge_embedding_text_v2(
            subject_id="u",
            predicate="LIKES",
            object_id="o",
            evidence_text=long_evidence,
        )
        evidence_line = [line for line in text.split("\n") if line.startswith("Evidence:")][0]
        assert len(evidence_line) < 600

    def test_unknown_predicate_fallback(self):
        text = build_l2_edge_embedding_text_v2(
            subject_id="user:alice",
            predicate="CUSTOM_PRED",
            object_id="thing:x",
            subject_name="Alice",
            object_name="X",
        )
        assert "Alice CUSTOM_PRED X" in text

    def test_v2_richer_than_v1(self):
        v1 = build_l2_edge_embedding_text(
            subject_id="user:alice",
            predicate="LIKES",
            object_id="food:pizza",
            subject_name="Alice",
            object_name="Pizza",
        )
        v2 = build_l2_edge_embedding_text_v2(
            subject_id="user:alice",
            predicate="LIKES",
            object_id="food:pizza",
            subject_name="Alice",
            object_name="Pizza",
            object_type="food",
            status="active",
        )
        assert len(v2) > len(v1)
