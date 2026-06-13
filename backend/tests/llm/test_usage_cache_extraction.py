"""Tests for cache/reasoning token capture in the provider bridge usage extractors.

Regression coverage for the bug where the extractors read non-existent SDK
attributes (``usage.cache_read_tokens`` / ``usage.reasoning_tokens``), so cache
read counts were always 0 and ``cached_input_per_million_tokens`` pricing never
applied. The extractors use ``getattr``, so ``SimpleNamespace`` faithfully mimics
the OpenAI ``CompletionUsage`` / Anthropic ``Usage`` SDK objects.
"""

from types import SimpleNamespace

import pytest

from magi.llm.pricing import calculate_chat_cost
from magi.llm.provider_bridge.responses import ProviderBridgeResponseMixin as M


# ---------------------------------------------------------------------------
# OpenAI non-streaming
# ---------------------------------------------------------------------------


def test_openai_usage_captures_cache_read_and_reasoning() -> None:
    resp = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=200,
            total_tokens=1200,
            prompt_tokens_details=SimpleNamespace(cached_tokens=800),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=50),
        )
    )

    usage = M._extract_openai_usage(resp)

    assert usage is not None
    # OpenAI's prompt_tokens already includes cached tokens — must NOT be adjusted.
    assert usage.prompt_tokens == 1000
    assert usage.completion_tokens == 200
    assert usage.total_tokens == 1200
    assert usage.cache_read_tokens == 800
    assert usage.reasoning_tokens == 50
    # OpenAI-compat has no cache-write count.
    assert usage.cache_write_tokens == 0


def test_openai_usage_without_details_does_not_crash() -> None:
    resp = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=200,
            total_tokens=1200,
        )
    )

    usage = M._extract_openai_usage(resp)

    assert usage is not None
    assert usage.prompt_tokens == 1000
    assert usage.cache_read_tokens == 0
    assert usage.reasoning_tokens == 0
    assert usage.cache_write_tokens == 0


def test_openai_usage_returns_none_when_absent() -> None:
    assert M._extract_openai_usage(SimpleNamespace()) is None


# ---------------------------------------------------------------------------
# OpenAI streaming
# ---------------------------------------------------------------------------


def test_openai_stream_usage_captures_cache_read_and_reasoning() -> None:
    usage_data = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=200,
        total_tokens=1200,
        prompt_tokens_details=SimpleNamespace(cached_tokens=800),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=50),
    )

    usage = M._extract_openai_stream_usage(usage_data)

    assert usage is not None
    assert usage.prompt_tokens == 1000
    assert usage.cache_read_tokens == 800
    assert usage.reasoning_tokens == 50
    assert usage.cache_write_tokens == 0


def test_openai_stream_usage_without_details_does_not_crash() -> None:
    usage_data = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )

    usage = M._extract_openai_stream_usage(usage_data)

    assert usage is not None
    assert usage.cache_read_tokens == 0
    assert usage.reasoning_tokens == 0


# ---------------------------------------------------------------------------
# Anthropic non-streaming
# ---------------------------------------------------------------------------


def test_anthropic_usage_folds_cache_into_prompt_tokens() -> None:
    resp = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=300,
            output_tokens=200,
            cache_read_input_tokens=2000,
            cache_creation_input_tokens=500,
        )
    )

    usage = M._extract_anthropic_usage(resp)

    assert usage is not None
    assert usage.cache_read_tokens == 2000
    assert usage.cache_write_tokens == 500
    # Anthropic input_tokens EXCLUDES cached + cache-creation; fold them back in
    # so pricing.py's min(prompt, cache_read) split is correct.
    assert usage.prompt_tokens == 2800
    assert usage.completion_tokens == 200
    assert usage.total_tokens == 3000
    assert usage.reasoning_tokens == 0


def test_anthropic_usage_without_cache_fields() -> None:
    resp = SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=40))

    usage = M._extract_anthropic_usage(resp)

    assert usage is not None
    assert usage.prompt_tokens == 100
    assert usage.cache_read_tokens == 0
    assert usage.cache_write_tokens == 0
    assert usage.total_tokens == 140


# ---------------------------------------------------------------------------
# Anthropic streaming fallback (no final_message)
# ---------------------------------------------------------------------------


def test_anthropic_stream_fallback_captures_cache_tokens() -> None:
    # _extract_anthropic_stream_usage is an instance method but only reads
    # `stream`/`usage_data`; a bare mixin instance suffices.
    mixin = M.__new__(M)
    stream = SimpleNamespace()  # no final_message attr → fallback branch
    usage_data = SimpleNamespace(
        input_tokens=300,
        output_tokens=200,
        cache_read_input_tokens=2000,
        cache_creation_input_tokens=500,
    )

    usage = mixin._extract_anthropic_stream_usage(stream, usage_data)

    assert usage is not None
    assert usage.cache_read_tokens == 2000
    assert usage.cache_write_tokens == 500
    assert usage.prompt_tokens == 2800
    assert usage.total_tokens == 3000


def test_anthropic_stream_final_message_delegates_to_non_stream_extractor() -> None:
    mixin = M.__new__(M)
    final_message = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=300,
            output_tokens=200,
            cache_read_input_tokens=2000,
            cache_creation_input_tokens=500,
        )
    )
    stream = SimpleNamespace(final_message=final_message)

    usage = mixin._extract_anthropic_stream_usage(stream, usage_data=None)

    assert usage is not None
    assert usage.cache_read_tokens == 2000
    assert usage.cache_write_tokens == 500
    assert usage.prompt_tokens == 2800


# ---------------------------------------------------------------------------
# End-to-end: cache_read_tokens now flows into pricing
# ---------------------------------------------------------------------------


def test_cache_read_tokens_drive_cached_pricing_for_qwen() -> None:
    """1M fully-cached prompt tokens bill at the cached rate, not the input rate.

    dashscope qwen3.7-plus: input 2.0 CNY/M, cached 0.4 CNY/M.
    """
    cached_amount, cached_currency = calculate_chat_cost(
        provider="dashscope",
        model="qwen3.7-plus",
        prompt_tokens=1_000_000,
        completion_tokens=0,
        cache_read_tokens=1_000_000,
    )
    uncached_amount, uncached_currency = calculate_chat_cost(
        provider="dashscope",
        model="qwen3.7-plus",
        prompt_tokens=1_000_000,
        completion_tokens=0,
        cache_read_tokens=0,
    )

    assert cached_currency == "CNY"
    assert uncached_currency == "CNY"
    assert cached_amount == pytest.approx(0.4)
    assert uncached_amount == pytest.approx(2.0)
    # The whole point: cached billing is materially cheaper now that
    # cache_read_tokens actually flows through.
    assert cached_amount < uncached_amount
