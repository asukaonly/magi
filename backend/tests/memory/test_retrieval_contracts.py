"""Tests for hybrid retrieval data contracts."""

from __future__ import annotations


import pytest

from magi.memory.hybrid_retrieval import build_query
from magi.memory.hybrid_retrieval.models import (
    L1Conditions,
    L2Conditions,
    L3Conditions,
    L4Conditions,
    RetrievalConfig,
)


class TestLayerConditions:
    def test_l1_defaults(self):
        c = L1Conditions(content_query="hello")
        assert c.event_types is None
        assert c.limit == 10

    def test_l2_defaults(self):
        c = L2Conditions()
        assert c.include_tom_snapshot is True
        assert c.include_relationships is True
        assert c.semantic_frame is None


    def test_l3_defaults(self):
        c = L3Conditions(content_query="summary")
        assert c.summary_types is None
        assert c.summary_categories is None
        assert c.limit == 5

    def test_l4_defaults(self):
        c = L4Conditions(content_query="skill")
        assert c.skill_categories is None
        assert c.limit == 5


class TestRetrievalQueryBackwardCompat:


    def test_build_query_rejects_legacy_recall_intent(self):
        with pytest.raises(TypeError, match="recall_intent"):
            build_query(query="test", recall_intent="event_recall")


class TestRetrievalConfig:
    def test_defaults(self):
        cfg = RetrievalConfig()
        assert cfg.default_max_tokens == 16384
        assert cfg.fallback_trigger_threshold == 1
        assert cfg.rrf_k == 60
        assert cfg.intent_decider_llm_enabled is True
