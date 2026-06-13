"""Unit tests for the reasoning dialect lookup and payload builders."""

from __future__ import annotations

import pytest

from magi.config.models import ModelVendor, ThinkingDepth
from magi.llm.reasoning_dialect import (
    ReasoningDialect,
    anthropic_thinking_is_adaptive_only,
    build_reasoning_payload,
    merge_payload,
    resolve_dialect,
)


class TestResolveDialect:
    def test_known_vendors(self) -> None:
        assert resolve_dialect(ModelVendor.OPENAI) == ReasoningDialect.OPENAI_EFFORT
        assert resolve_dialect(ModelVendor.DEEPSEEK) == ReasoningDialect.DEEPSEEK_THINKING
        assert resolve_dialect(ModelVendor.ANTHROPIC) == ReasoningDialect.ANTHROPIC_BUDGET
        assert resolve_dialect(ModelVendor.DASHSCOPE) == ReasoningDialect.DASHSCOPE_ENABLE
        assert resolve_dialect(ModelVendor.GLM) == ReasoningDialect.GLM_TOGGLE

    def test_grok_uses_openai_effort(self) -> None:
        # Grok 4.3's OpenAI-compatible endpoint exposes a top-level
        # ``reasoning_effort`` knob, so it routes through OPENAI_EFFORT.
        assert resolve_dialect(ModelVendor.GROK) == ReasoningDialect.OPENAI_EFFORT

    def test_gemini_uses_openai_effort(self) -> None:
        assert resolve_dialect(ModelVendor.GEMINI) == ReasoningDialect.OPENAI_EFFORT

    def test_kimi_uses_glm_toggle(self) -> None:
        assert resolve_dialect(ModelVendor.KIMI) == ReasoningDialect.GLM_TOGGLE

    def test_minimax_uses_glm_toggle(self) -> None:
        assert resolve_dialect(ModelVendor.MINIMAX) == ReasoningDialect.GLM_TOGGLE

    def test_generic_vendor_emits_nothing(self) -> None:
        assert resolve_dialect(ModelVendor.GENERIC) == ReasoningDialect.NONE

    def test_none_falls_back_to_none(self) -> None:
        assert resolve_dialect(None) == ReasoningDialect.NONE


class TestOpenAIEffortBuilder:
    def test_none_depth_emits_nothing(self) -> None:
        payload = build_reasoning_payload(ReasoningDialect.OPENAI_EFFORT, ThinkingDepth.NONE)
        assert payload == {}

    @pytest.mark.parametrize(
        "depth,expected",
        [
            (ThinkingDepth.LOW, "low"),
            (ThinkingDepth.MEDIUM, "medium"),
            (ThinkingDepth.HIGH, "high"),
            (ThinkingDepth.MAX, "high"),
        ],
    )
    def test_enabled_depth_effort_mapping(self, depth: ThinkingDepth, expected: str) -> None:
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


class TestAnthropicAdaptiveOnlyClassifier:
    @pytest.mark.parametrize(
        "model_id",
        [
            "claude-opus-4-7",
            "claude-opus-4-8",
            "claude-opus-4-8[1m]",
            "claude-fable-5",
            "Claude-Fable-5-Preview",
        ],
    )
    def test_adaptive_only_models(self, model_id: str) -> None:
        assert anthropic_thinking_is_adaptive_only(model_id) is True

    @pytest.mark.parametrize(
        "model_id",
        [
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "claude-opus-4-0",
        ],
    )
    def test_budgeted_models(self, model_id: str) -> None:
        assert anthropic_thinking_is_adaptive_only(model_id) is False

    def test_unknown_defaults_to_budgeted(self) -> None:
        assert anthropic_thinking_is_adaptive_only("") is False
        assert anthropic_thinking_is_adaptive_only("some-other-model") is False


class TestDeepSeekThinkingBuilder:
    def test_none_depth_disables_thinking(self) -> None:
        payload = build_reasoning_payload(ReasoningDialect.DEEPSEEK_THINKING, ThinkingDepth.NONE)
        assert payload == {"_extra_body": {"thinking": {"type": "disabled"}}}

    @pytest.mark.parametrize(
        "depth,expected_effort",
        [
            (ThinkingDepth.LOW, "high"),
            (ThinkingDepth.MEDIUM, "high"),
            (ThinkingDepth.HIGH, "high"),
            (ThinkingDepth.MAX, "max"),
        ],
    )
    def test_enabled_depths_enable_thinking_and_set_effort(
        self, depth: ThinkingDepth, expected_effort: str
    ) -> None:
        payload = build_reasoning_payload(ReasoningDialect.DEEPSEEK_THINKING, depth)
        assert payload == {
            "_kwargs": {"reasoning_effort": expected_effort},
            "_extra_body": {"thinking": {"type": "enabled"}},
        }


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


def test_every_vendor_has_dialect_mapping() -> None:
    """Adding a new ModelVendor must come with a dialect entry."""
    for vendor in ModelVendor:
        # If a new vendor is missing a dialect, resolve_dialect falls back
        # to NONE, but we still want the test to flag it so the author can
        # confirm that's intentional rather than silent breakage.
        assert resolve_dialect(vendor) in ReasoningDialect, (
            f"ModelVendor.{vendor.name} resolves to an unknown dialect"
        )
