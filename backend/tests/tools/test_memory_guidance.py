"""Tests for memory guidance trigger restructure."""

import pytest

from magi.tools.context_routing.memory_guidance import (
    MEMORY_RETRIEVAL_TRIGGERS,
    MEMORY_RETRIEVAL_TRIGGERS_BY_CATEGORY,
    evaluate_memory_need,
)


class TestTriggerCategories:
    def test_all_categories_populated(self):
        assert len(MEMORY_RETRIEVAL_TRIGGERS_BY_CATEGORY) >= 6

    def test_flat_list_backward_compatible(self):
        assert len(MEMORY_RETRIEVAL_TRIGGERS) > 20
        assert "i like" in MEMORY_RETRIEVAL_TRIGGERS

    def test_personal_recall_triggers(self):
        result = evaluate_memory_need("what did i eat yesterday", {})
        assert result is not None
        assert result.route == "explicit_query"

    def test_preference_triggers(self):
        result = evaluate_memory_need("i like pizza", {})
        assert result is not None

    def test_temporal_triggers(self):
        result = evaluate_memory_need("what happened last week", {})
        assert result is not None

    def test_chinese_triggers(self):
        result = evaluate_memory_need("我喜欢吃什么", {})
        assert result is not None

    def test_no_match_returns_none(self):
        result = evaluate_memory_need("please compile this code", {})
        assert result is None


class TestEntityRecallSuppression:
    def test_entity_recall_in_normal_chat(self):
        result = evaluate_memory_need("who is Alice", {})
        assert result is not None

    def test_entity_recall_suppressed_in_code_context(self):
        result = evaluate_memory_need(
            "who is this variable",
            {},
            task_category="code_execution",
        )
        assert result is None

    def test_entity_recall_suppressed_in_debugging(self):
        result = evaluate_memory_need(
            "where is this function defined",
            {},
            task_category="debugging",
        )
        assert result is None

    def test_other_categories_not_suppressed_in_code(self):
        result = evaluate_memory_need(
            "i like python",
            {},
            task_category="code_execution",
        )
        assert result is not None
