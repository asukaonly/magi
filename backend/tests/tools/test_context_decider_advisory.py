"""Tests for L4 tool advisory injection into ContextDecider prompt."""
from __future__ import annotations

import pytest

from magi.tools.context_decider import ContextDecider
from magi.tools.context_decider_context import ContextDeciderContext


class TestContextDeciderAdvisoryPrompt:
    """Verify that ContextDecider._build_prompt renders advisory correctly."""

    def _build(self, advisory: list[dict]) -> str:
        """Helper: build a prompt with given advisory using a minimal ContextDecider."""
        decider = ContextDecider.__new__(ContextDecider)
        decider.tool_registry = type("R", (), {"_skills": {}})()
        ctx = ContextDeciderContext(tool_advisory=advisory)
        return decider._build_prompt("hello", [], ctx)

    def test_no_advisory_no_section(self):
        prompt = self._build([])
        assert "Tool Experience Notes" not in prompt

    def test_advisory_section_rendered(self):
        advisory = [
            {
                "tool_name": "web_search",
                "available": True,
                "breaker_state": "closed",
                "success_rate": 0.9,
                "total_attempts": 10,
                "strategy_hint": "Use quoted terms",
                "context_fit": None,
                "risk_note": None,
            }
        ]
        prompt = self._build(advisory)
        assert "## Tool Experience Notes" in prompt
        assert "web_search" in prompt
        assert "success 90% over 10 uses" in prompt
        assert "tip: Use quoted terms" in prompt

    def test_unavailable_tool_marked(self):
        advisory = [
            {
                "tool_name": "flaky_api",
                "available": False,
                "breaker_state": "open",
                "success_rate": 0.0,
                "total_attempts": 5,
                "strategy_hint": None,
                "context_fit": None,
                "risk_note": "Circuit breaker open: consecutive failures detected",
            }
        ]
        prompt = self._build(advisory)
        assert "UNAVAILABLE" in prompt
        assert "flaky_api" in prompt
        assert "risk:" in prompt

    def test_multiple_advisories(self):
        advisory = [
            {
                "tool_name": "tool_a",
                "available": True,
                "breaker_state": "closed",
                "success_rate": 0.5,
                "total_attempts": 4,
                "strategy_hint": None,
                "context_fit": None,
                "risk_note": "Low success rate (50% over 4 attempts)",
            },
            {
                "tool_name": "tool_b",
                "available": True,
                "breaker_state": "half_open",
                "success_rate": 0.7,
                "total_attempts": 10,
                "strategy_hint": "Best for CSV files",
                "context_fit": None,
                "risk_note": "Circuit breaker recovering: recent failures observed",
            },
        ]
        prompt = self._build(advisory)
        assert "tool_a" in prompt
        assert "tool_b" in prompt
        assert "Best for CSV files" in prompt

    def test_advisory_placed_before_json_instruction(self):
        advisory = [
            {
                "tool_name": "tool_x",
                "available": True,
                "breaker_state": "closed",
                "success_rate": 1.0,
                "total_attempts": 2,
                "strategy_hint": "hint",
                "context_fit": None,
                "risk_note": None,
            }
        ]
        prompt = self._build(advisory)
        notes_idx = prompt.index("Tool Experience Notes")
        json_idx = prompt.index("Respond with ONLY the JSON object")
        assert notes_idx < json_idx
