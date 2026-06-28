"""Tests for routing in context_routing.

Phase B.11: Tests for keyword-based normalization (default_orchestration_strategy,
normalize_orchestration_strategy) have been deleted — those helpers are removed.
Routing coverage now lives in test_route_decision.py via OrchestrationPlan.
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


# ADR-0005 / f9c40b9b slimmed the prompt to a single consumed-only schema:
# leaf types (default_leaf_type / "Coding") are gone — coding routing is the
# lowercase `coding` PROFILE, and decomposition policy is the orchestration
# escalation + CodeExplore external-evidence rule.


def test_system_prompt_advertises_coding_in_schema() -> None:
    from magi.tools.context_decider_system_prompt import CONTEXT_DECIDER_SYSTEM_PROMPT

    assert '"profile": "chat|research|explore|coding|media|system"' in CONTEXT_DECIDER_SYSTEM_PROMPT


def test_system_prompt_has_coding_few_shot() -> None:
    from magi.tools.context_decider_system_prompt import CONTEXT_DECIDER_SYSTEM_PROMPT

    coding_blocks = [
        block
        for block in CONTEXT_DECIDER_SYSTEM_PROMPT.split("\n\n")
        if '"profile": "coding"' in block
    ]
    assert coding_blocks, "no coding few-shot found"
    for block in coding_blocks:
        assert '"agent"' in block, f"coding few-shot must include agent tool: {block!r}"


def test_system_prompt_has_external_decomposition_policy() -> None:
    from magi.tools.context_decider_system_prompt import CONTEXT_DECIDER_SYSTEM_PROMPT

    # CodeExplore stays on local evidence; external-world work goes to the
    # research/web path, escalating to orchestration only for decomposable
    # multi-part work.
    assert "other external-world evidence" in CONTEXT_DECIDER_SYSTEM_PROMPT
    assert "decomposable multi-part work" in CONTEXT_DECIDER_SYSTEM_PROMPT
    assert '"tools": ["web-search"]' in CONTEXT_DECIDER_SYSTEM_PROMPT
