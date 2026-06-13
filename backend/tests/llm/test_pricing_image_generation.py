"""calculate_image_generation_cost pricing in the model's native currency."""
from __future__ import annotations

import pytest

from magi.llm.pricing import calculate_image_generation_cost


def test_dashscope_qwen_image_cost_in_cny() -> None:
    amount, currency = calculate_image_generation_cost(
        provider="dashscope",
        model="qwen-image-2.0-pro",
        image_count=3,
    )
    # qwen-image-2.0-pro is 0.5 CNY / image -> 3 images = 1.5 CNY.
    assert amount == pytest.approx(1.5)
    assert currency == "CNY"


def test_unknown_image_model_returns_none() -> None:
    assert calculate_image_generation_cost(
        provider="dashscope",
        model="does-not-exist",
        image_count=3,
    ) == (None, None)


def test_zero_images_is_zero_cost_not_none() -> None:
    amount, currency = calculate_image_generation_cost(
        provider="dashscope",
        model="qwen-image-2.0-pro",
        image_count=0,
    )
    assert amount == pytest.approx(0.0)
    assert currency == "CNY"
