"""Unit tests for the reasoning dialect lookup and payload builders."""

from __future__ import annotations

import pytest

from magi.config.models import ThinkingDepth
from magi.llm.reasoning_dialect import (
    DEFAULT_PROVIDER_DIALECTS,
    ReasoningDialect,
    build_reasoning_payload,
    merge_payload,
    resolve_dialect,
)


class TestResolveDialect:
    def test_known_provider(self) -> None:
        assert resolve_dialect("openai") == ReasoningDialect.OPENAI_EFFORT
        assert resolve_dialect("anthropic") == ReasoningDialect.ANTHROPIC_BUDGET
        assert resolve_dialect("dashscope") == ReasoningDialect.DASHSCOPE_ENABLE
        assert resolve_dialect("glm") == ReasoningDialect.GLM_TOGGLE
        assert resolve_dialect("glm_codeplan") == ReasoningDialect.GLM_TOGGLE

    def test_grok_explicitly_none_not_openai_effort(self) -> None:
        # Historical regression: the old if/elif chain used
        # `provider != "grok"` as a *negative* exception inside the
        # OpenAI-effort branch. Grok must not silently pick up
        # reasoning_effort just because no dedicated dialect is wired.
        assert resolve_dialect("grok") == ReasoningDialect.NONE

    def test_unknown_provider_falls_back_to_none(self) -> None:
        assert resolve_dialect("totally-new-vendor") == ReasoningDialect.NONE
        assert resolve_dialect("") == ReasoningDialect.NONE
        assert resolve_dialect(None) == ReasoningDialect.NONE  # type: ignore[arg-type]

    def test_normalizes_case(self) -> None:
        assert resolve_dialect("OpenAI") == ReasoningDialect.OPENAI_EFFORT
        assert resolve_dialect("  GLM  ") == ReasoningDialect.GLM_TOGGLE


class TestOpenAIEffortBuilder:
    @pytest.mark.parametrize(
        "depth,expected",
        [
            (ThinkingDepth.NONE, "none"),
            (ThinkingDepth.LOW, "low"),
            (ThinkingDepth.MEDIUM, "medium"),
            (ThinkingDepth.HIGH, "high"),
            (ThinkingDepth.MAX, "high"),
        ],
    )
    def test_effort_mapping(self, depth: ThinkingDepth, expected: str) -> None:
        payload = build_reasoning_payload(ReasoningDialect.OPENAI_EFFORT, depth)
        assert payload == {"_kwargs": {"reasoning_effort": expected}}


class TestAnthropicBudgetBuilder:
    @pytest.mark.parametrize(
        "depth,expected_tokens",
        [
            (ThinkingDepth.LOW, 2048),
            (ThinkingDepth.MEDIUM, 8192),
            (ThinkingDepth.HIGH, 16384),
            (ThinkingDepth.MAX, 32768),
        ],
    )
    def test_enabled_depth_emits_budget(self, depth: ThinkingDepth, expected_tokens: int) -> None:
        payload = build_reasoning_payload(ReasoningDialect.ANTHROPIC_BUDGET, depth)
        assert payload == {
            "_kwargs": {"thinking": {"type": "enabled", "budget_tokens": expected_tokens}}
        }

    def test_none_depth_emits_nothing(self) -> None:
        assert build_reasoning_payload(ReasoningDialect.ANTHROPIC_BUDGET, ThinkingDepth.NONE) == {}


class TestDashScopeEnableBuilder:
    def test_none_disables(self) -> None:
        payload = build_reasoning_payload(ReasoningDialect.DASHSCOPE_ENABLE, ThinkingDepth.NONE)
        assert payload == {"_extra_body": {"enable_thinking": False}}

    def test_any_depth_enables(self) -> None:
        for depth in (ThinkingDepth.LOW, ThinkingDepth.MEDIUM, ThinkingDepth.HIGH, ThinkingDepth.MAX):
            payload = build_reasoning_payload(ReasoningDialect.DASHSCOPE_ENABLE, depth)
            assert payload == {"_extra_body": {"enable_thinking": True}}


class TestGlmToggleBuilder:
    def test_none_disables(self) -> None:
        payload = build_reasoning_payload(ReasoningDialect.GLM_TOGGLE, ThinkingDepth.NONE)
        assert payload == {"_extra_body": {"thinking": {"type": "disabled"}}}

    def test_any_other_depth_emits_nothing(self) -> None:
        for depth in (ThinkingDepth.LOW, ThinkingDepth.MEDIUM, ThinkingDepth.HIGH, ThinkingDepth.MAX):
            assert build_reasoning_payload(ReasoningDialect.GLM_TOGGLE, depth) == {}


class TestNoneBuilder:
    def test_emits_nothing_for_every_depth(self) -> None:
        for depth in ThinkingDepth:
            assert build_reasoning_payload(ReasoningDialect.NONE, depth) == {}


class TestMergePayload:
    def test_merges_kwargs(self) -> None:
        kwargs = {"existing": "value"}
        merged = merge_payload(kwargs, {"_kwargs": {"reasoning_effort": "high"}})
        assert merged is kwargs
        assert merged == {"existing": "value", "reasoning_effort": "high"}

    def test_merges_extra_body_preserving_existing(self) -> None:
        kwargs = {"extra_body": {"foo": 1}}
        merge_payload(kwargs, {"_extra_body": {"enable_thinking": True}})
        assert kwargs["extra_body"] == {"foo": 1, "enable_thinking": True}

    def test_merges_both_kwargs_and_extra_body(self) -> None:
        kwargs: dict = {}
        merge_payload(
            kwargs,
            {"_kwargs": {"top": 1}, "_extra_body": {"nested": 2}},
        )
        assert kwargs == {"top": 1, "extra_body": {"nested": 2}}

    def test_empty_payload_is_noop(self) -> None:
        kwargs = {"a": 1}
        merge_payload(kwargs, {})
        assert kwargs == {"a": 1}


def test_default_provider_dialects_covers_known_provider_enum() -> None:
    """Any provider name in LLMProvider should have a default dialect."""
    from magi.config.models import LLMProvider

    for member in LLMProvider:
        if member == LLMProvider.CUSTOM:
            # custom routes through ScenarioLLMPool runtime detection
            continue
        assert member.value in DEFAULT_PROVIDER_DIALECTS, (
            f"LLMProvider.{member.name} has no default reasoning dialect — "
            "add it to DEFAULT_PROVIDER_DIALECTS or call out the omission."
        )
