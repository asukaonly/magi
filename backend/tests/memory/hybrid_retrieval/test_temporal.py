"""Tests for temporal SQL clause builders."""

import time

import pytest

from magi.memory.hybrid_retrieval.temporal import (
    build_assertion_temporal_clause,
    build_episode_temporal_clause,
    build_knowledge_temporal_clause,
    compute_temporal_score,
)
from magi.memory.hybrid_retrieval.models import TemporalContext


class TestBuildKnowledgeTemporalClause:
    def test_none_returns_empty(self):
        clause, params = build_knowledge_temporal_clause(None)
        assert clause == ""
        assert params == []

    def test_mode_none_returns_empty(self):
        tc = TemporalContext(mode="none")
        clause, params = build_knowledge_temporal_clause(tc)
        assert clause == ""
        assert params == []

    def test_current_mode(self):
        tc = TemporalContext(mode="current")
        clause, params = build_knowledge_temporal_clause(tc)
        assert "status = ?" in clause
        assert "expires_at" in clause
        assert params[0] == "active"

    def test_as_of_mode(self):
        anchor = time.time() - 86400
        tc = TemporalContext(mode="as_of", anchor=anchor)
        clause, params = build_knowledge_temporal_clause(tc)
        assert "first_observed_at <= ?" in clause
        assert "deprecated_at" in clause
        assert anchor in params

    def test_during_mode(self):
        now = time.time()
        tc = TemporalContext(mode="during", start=now - 86400, end=now)
        clause, params = build_knowledge_temporal_clause(tc)
        assert "first_observed_at <= ?" in clause
        assert "last_observed_at >= ?" in clause


class TestBuildAssertionTemporalClause:
    def test_current_mode(self):
        tc = TemporalContext(mode="current")
        clause, params = build_assertion_temporal_clause(tc)
        assert "validation_state IN" in clause

    def test_as_of_mode(self):
        anchor = time.time() - 86400
        tc = TemporalContext(mode="as_of", anchor=anchor)
        clause, params = build_assertion_temporal_clause(tc)
        assert "first_inferred_at <= ?" in clause
        assert "superseded_at" in clause


class TestBuildEpisodeTemporalClause:
    def test_during_mode(self):
        now = time.time()
        tc = TemporalContext(mode="during", start=now - 86400, end=now)
        clause, params = build_episode_temporal_clause(tc)
        assert "time_start <= ?" in clause
        assert "time_end >= ?" in clause


class TestComputeTemporalScore:
    def test_none_returns_full_score(self):
        assert compute_temporal_score(None) == 1.0

    def test_current_recent_item(self):
        tc = TemporalContext(mode="current")
        score = compute_temporal_score(tc, last_observed=time.time() - 3600)
        assert score == 1.0

    def test_current_old_item(self):
        tc = TemporalContext(mode="current")
        score = compute_temporal_score(tc, last_observed=time.time() - 200 * 86400)
        assert score < 0.5

    def test_as_of_item_after_anchor(self):
        anchor = time.time() - 86400
        tc = TemporalContext(mode="as_of", anchor=anchor)
        score = compute_temporal_score(tc, first_observed=time.time())
        assert score == 0.0

    def test_during_full_overlap(self):
        now = time.time()
        tc = TemporalContext(mode="during", start=now - 86400, end=now)
        score = compute_temporal_score(
            tc, first_observed=now - 86400, last_observed=now
        )
        assert score == 1.0
