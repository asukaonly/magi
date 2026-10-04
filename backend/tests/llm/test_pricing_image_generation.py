"""calculate_image_generation_cost pricing in the model's native currency."""
from __future__ import annotations

import pytest

from magi.llm.pricing import calculate_image_generation_cost


@pytest.mark.parametrize(
    "case_image_count,case_expected_cost",
    [
        pytest.param(3, 1.5, id="dashscope_qwen_image_cost_in_cny"),
        pytest.param(0, 0.0, id="zero_images_is_zero_cost_not_none"),
    ],
)
def test_image_cost_handles_positive_and_zero_usage(case_image_count, case_expected_cost) -> None:
    amount, currency = calculate_image_generation_cost(
        provider="dashscope", model="qwen-image-2.0-pro", image_count=case_image_count
    )
    assert amount == pytest.approx(case_expected_cost)
    assert currency == "CNY"


def test_unknown_image_model_returns_none() -> None:
    assert calculate_image_generation_cost(
        provider="dashscope",
        model="does-not-exist",
        image_count=3,
    ) == (None, None)
