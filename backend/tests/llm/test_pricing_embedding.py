"""calculate_embedding_cost pricing in the model's native currency."""
from __future__ import annotations

import pytest

from magi.llm.pricing import calculate_embedding_cost


def test_dashscope_text_embedding_v3_cost_in_cny() -> None:
    amount, currency = calculate_embedding_cost(
        provider="dashscope",
        model="text-embedding-v3",
        prompt_tokens=1_000_000,
    )
    # text-embedding-v3 input is 0.5 CNY / million tokens.
    assert amount == pytest.approx(0.5)
    assert currency == "CNY"


def test_unknown_embedding_model_returns_none() -> None:
    assert calculate_embedding_cost(
        provider="dashscope",
        model="does-not-exist",
        prompt_tokens=1_000_000,
    ) == (None, None)


def test_zero_tokens_is_zero_cost_not_none() -> None:
    amount, currency = calculate_embedding_cost(
        provider="dashscope",
        model="text-embedding-v3",
        prompt_tokens=0,
    )
    assert amount == pytest.approx(0.0)
    assert currency == "CNY"
