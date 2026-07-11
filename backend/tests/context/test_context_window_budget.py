from __future__ import annotations

from magi.context.window_budget import build_context_window_budget, estimate_context_tokens
from magi.llm.model_context import ModelContextProfile


def test_large_model_uses_half_of_input_capacity() -> None:
    budget = build_context_window_budget(
        ModelContextProfile(
            provider_id="anthropic",
            model_id="claude-sonnet-4-6",
            context_window=1_000_000,
            max_output_tokens=64_000,
        )
    )

    assert budget.context_window == 1_000_000
    assert budget.input_capacity == 936_000
    assert budget.compaction_trigger_tokens == 468_000
    assert budget.recent_tail_tokens == 93_600
    assert budget.uses_fallback is False


def test_small_model_uses_three_quarters_of_input_capacity() -> None:
    budget = build_context_window_budget(
        ModelContextProfile(
            provider_id="local",
            model_id="small-model",
            context_window=200_000,
            max_output_tokens=8_000,
        )
    )

    assert budget.input_capacity == 192_000
    assert budget.compaction_trigger_tokens == 144_000
    assert budget.recent_tail_tokens == 28_800


def test_unknown_capacity_uses_observable_conservative_fallback() -> None:
    budget = build_context_window_budget(
        ModelContextProfile(
            provider_id="custom",
            model_id="unknown-model",
            context_window=None,
            max_output_tokens=None,
        )
    )

    assert budget.context_window == 128_000
    assert budget.input_capacity == 119_808
    assert budget.compaction_trigger_tokens == 89_856
    assert budget.uses_fallback is True


def test_context_token_estimate_counts_structured_payload() -> None:
    small = estimate_context_tokens({"system": "short", "tools": []})
    large = estimate_context_tokens({"system": "x" * 4_000, "tools": []})

    assert small >= 1
    assert large > small
