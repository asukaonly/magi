"""Tests for routing in context_routing.

Phase B.11: Tests for keyword-based normalization (default_orchestration_strategy,
normalize_orchestration_strategy) have been deleted — those helpers are removed.
Routing coverage now lives in test_route_decision.py via RouteDecision.to_legacy_strategy_dict().
Tests for guardrail helpers (should_decompose_external_request) and system prompt
content are retained here.
"""

from __future__ import annotations

import pytest

from magi.tools.context_routing.research_guardrail import should_decompose_external_request


def test_external_decomposition_policy_requires_research_breadth() -> None:
    assert not should_decompose_external_request(
        "plan a low-walking itinerary with metro and lunch"
    )
    assert should_decompose_external_request(
        "compare sources and give citations for a research report"
    )


def test_system_prompt_advertises_coding_in_schema() -> None:
    from magi.tools.context_decider_system_prompt import CONTEXT_DECIDER_SYSTEM_PROMPT

    assert "Coding" in CONTEXT_DECIDER_SYSTEM_PROMPT
    assert (
        '"default_leaf_type": "CodeExplore|general-purpose|Coding"' in CONTEXT_DECIDER_SYSTEM_PROMPT
    )


def test_system_prompt_has_coding_few_shot() -> None:
    from magi.tools.context_decider_system_prompt import CONTEXT_DECIDER_SYSTEM_PROMPT

    assert '"default_leaf_type": "Coding"' in CONTEXT_DECIDER_SYSTEM_PROMPT
    coding_blocks = [
        block
        for block in CONTEXT_DECIDER_SYSTEM_PROMPT.split("\n\n")
        if '"default_leaf_type": "Coding"' in block
    ]
    assert coding_blocks, "no Coding few-shot found"
    for block in coding_blocks:
        assert '"agent"' in block, f"Coding few-shot must include agent tool: {block!r}"


def test_system_prompt_has_external_decomposition_policy() -> None:
    from magi.tools.context_decider_system_prompt import CONTEXT_DECIDER_SYSTEM_PROMPT

    assert "Decompose external-world work only" in CONTEXT_DECIDER_SYSTEM_PROMPT
    assert "Bounded planning/advice" in CONTEXT_DECIDER_SYSTEM_PROMPT
    assert '"tools": ["web-search"]' in CONTEXT_DECIDER_SYSTEM_PROMPT
