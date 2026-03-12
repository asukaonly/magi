"""Tests for ContextDecider memory retrieval guidance."""
import pytest
from unittest.mock import MagicMock, AsyncMock


class TestContextDeciderMemoryGuidance:
    """Tests for memory retrieval guidance in ContextDecider."""

    def test_evaluate_memory_need_time_based_query(self):
        """Should detect memory retrieval need for time-based queries."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        llm_adapter = MagicMock()
        decider = ContextDecider(tool_registry, llm_adapter)

        guidance = decider.evaluate_memory_need(
            "What did I browse yesterday?",
            {"current_date": "2024-01-15"}
        )

        assert guidance is not None
        assert guidance.inject_prompt is True
        assert "memory_query" in [t.name for t in guidance.recommended_tools]

    def test_evaluate_memory_need_browsing_pattern(self):
        """Should detect memory retrieval for browsing pattern queries."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        llm_adapter = MagicMock()
        decider = ContextDecider(tool_registry, llm_adapter)

        guidance = decider.evaluate_memory_need(
            "Analyze my browsing patterns this week",
            {"current_date": "2024-01-15"}
        )

        assert guidance is not None
        assert "memory_query" in [t.name for t in guidance.recommended_tools]

    def test_evaluate_memory_need_no_need(self):
        """Should not trigger for queries that don't need memory."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        llm_adapter = MagicMock()
        decider = ContextDecider(tool_registry, llm_adapter)

        guidance = decider.evaluate_memory_need(
            "What is the weather in Tokyo?",
            {}
        )

        # Weather query doesn't need personal memory
        assert guidance is None
