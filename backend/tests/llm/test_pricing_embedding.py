"""calculate_embedding_cost pricing in the model's native currency."""
from __future__ import annotations

import pytest

from magi.llm.pricing import calculate_embedding_cost


@pytest.mark.parametrize(
    "case_input_tokens,case_expected_cost",
    [
        pytest.param(1000000, 0.5, id="dashscope_text_embedding_v3_cost_in_cny"),
        pytest.param(0, 0.0, id="zero_tokens_is_zero_cost_not_none"),
    ],
)
def test_embedding_cost_handles_positive_and_zero_usage(
    case_input_tokens, case_expected_cost
) -> None:
    amount, currency = calculate_embedding_cost(
        provider="dashscope", model="text-embedding-v3", prompt_tokens=case_input_tokens
    )
    assert amount == pytest.approx(case_expected_cost)
    assert currency == "CNY"


def test_unknown_embedding_model_returns_none() -> None:
    assert calculate_embedding_cost(
        provider="dashscope",
        model="does-not-exist",
        prompt_tokens=1_000_000,
    ) == (None, None)
