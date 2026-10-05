from __future__ import annotations

import pytest

from magi.context.window_budget import (
    GENERAL_SUMMARY_OUTPUT_PROFILE,
    PERSONA_SUMMARY_OUTPUT_PROFILE,
    build_context_window_budget,
    estimate_context_tokens,
    measure_context_window_usage,
    measure_provider_prompt_usage,
    resolve_summary_output_tokens,
)
from magi.llm.model_context import ModelContextProfile


@pytest.mark.parametrize(
    "window,output,capacity,trigger,tail",
    [(1_000_000, 64_000, 936_000, 468_000, 93_600), (200_000, 8_000, 192_000, 144_000, 28_800)],
)
def test_known_model_capacity_controls_compaction_policy(window, output, capacity, trigger, tail):
    budget = build_context_window_budget(
        ModelContextProfile(
            provider_id="test", model_id="known", context_window=window, max_output_tokens=output
        )
    )
    assert budget.context_window == window
    assert (budget.input_capacity, budget.compaction_trigger_tokens, budget.recent_tail_tokens) == (
        capacity,
        trigger,
        tail,
    )
    assert budget.uses_fallback is False


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


def test_context_token_estimate_is_more_conservative_for_non_ascii_text() -> None:
    ascii_text = estimate_context_tokens("a" * 400)
    chinese_text = estimate_context_tokens("你" * 400)

    assert 90 <= ascii_text <= 110
    assert chinese_text > ascii_text * 3


def test_context_usage_distinguishes_trigger_from_hard_capacity() -> None:
    budget = build_context_window_budget(
        ModelContextProfile(
            provider_id="local",
            model_id="small-model",
            context_window=1_000,
            max_output_tokens=100,
        )
    )

    empty = measure_context_window_usage(budget, [])
    small = measure_context_window_usage(budget, {"prompt": "short"})
    pressured = measure_context_window_usage(
        budget,
        {"prompt": "x" * 2_800},
    )
    oversized = measure_context_window_usage(
        budget,
        {"prompt": "x" * 4_000},
    )

    assert pressured.requires_compaction is True
    assert pressured.fits_input_capacity is True
    assert oversized.fits_input_capacity is False

    assert empty.estimated_tokens == 1
    assert 1 <= small.estimated_tokens < pressured.estimated_tokens < oversized.estimated_tokens
    assert small.requires_compaction is False and small.fits_input_capacity is True


def test_context_usage_keeps_provider_count_as_lower_bound() -> None:
    budget = build_context_window_budget(
        ModelContextProfile(
            provider_id="local",
            model_id="small-model",
            context_window=2_000,
            max_output_tokens=200,
        )
    )

    usage = measure_context_window_usage(
        budget,
        {"prompt": "short"},
        observed_input_tokens=1_500,
    )

    assert usage.estimated_tokens == 1_500
    assert usage.requires_compaction is True


def test_provider_prompt_usage_does_not_count_inline_image_bytes_as_text() -> None:
    budget = build_context_window_budget(
        ModelContextProfile(
            provider_id="local",
            model_id="vision-model",
            context_window=128_000,
            max_output_tokens=8_192,
        )
    )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image."},
                {
                    "type": "image",
                    "mime_type": "image/png",
                    "data": "A" * 600_000,
                },
            ],
        }
    ]

    usage = measure_provider_prompt_usage(
        budget,
        messages,
        prompt_overhead={"system_prompt": "system", "tools": []},
    )

    assert usage.estimated_tokens < 10_000
    assert usage.requires_compaction is False
    assert messages[0]["content"][1]["data"] == "A" * 600_000


def test_summary_output_budget_uses_destination_capacity_and_purpose() -> None:
    source_budget = build_context_window_budget(
        ModelContextProfile(
            provider_id="core",
            model_id="small-core-model",
            context_window=32_000,
            max_output_tokens=8_000,
        )
    )
    summary_model_budget = build_context_window_budget(
        ModelContextProfile(
            provider_id="summary",
            model_id="large-summary-model",
            context_window=1_000_000,
            max_output_tokens=64_000,
        )
    )

    assert (
        resolve_summary_output_tokens(
            source_budget,
            summary_model_budget,
            profile=GENERAL_SUMMARY_OUTPUT_PROFILE,
        )
        == 1_200
    )
    assert (
        resolve_summary_output_tokens(
            source_budget,
            summary_model_budget,
            profile=PERSONA_SUMMARY_OUTPUT_PROFILE,
        )
        == 512
    )


def test_summary_output_budget_never_exceeds_writer_model() -> None:
    source_budget = build_context_window_budget(
        ModelContextProfile(
            provider_id="core",
            model_id="large-core-model",
            context_window=1_000_000,
            max_output_tokens=64_000,
        )
    )
    summary_model_budget = build_context_window_budget(
        ModelContextProfile(
            provider_id="summary",
            model_id="tiny-summary-model",
            context_window=4_000,
            max_output_tokens=300,
        )
    )

    assert resolve_summary_output_tokens(source_budget, summary_model_budget) == 300
