"""Provider token accounting across response and streaming entry points."""

from dataclasses import asdict
from types import SimpleNamespace as NS
import pytest
from magi.llm.pricing import calculate_chat_cost
from magi.llm.provider_bridge.responses import ProviderBridgeResponseMixin as M


@pytest.mark.parametrize("entry", ["response", "stream"])
@pytest.mark.parametrize(
    "details,read,write,reasoning,seen",
    [
        ({}, 0, 0, 0, False),
        ({"prompt_tokens_details": None, "completion_tokens_details": None}, 0, 0, 0, False),
        (
            {
                "prompt_tokens_details": NS(cached_tokens=800),
                "completion_tokens_details": NS(reasoning_tokens=50),
            },
            800,
            0,
            50,
            True,
        ),
        ({"prompt_cache_hit_tokens": 800, "prompt_cache_miss_tokens": 200}, 800, 0, 0, True),
        (
            {"prompt_tokens_details": NS(cached_tokens=0, cache_creation_input_tokens=900)},
            0,
            900,
            0,
            True,
        ),
    ],
    ids=["missing", "null", "nested-cache", "top-level-cache", "cache-creation"],
)
def test_openai_token_accounting(entry, details, read, write, reasoning, seen):
    raw = NS(prompt_tokens=1000, completion_tokens=200, total_tokens=1200, **details)
    usage = (
        M._extract_openai_usage(NS(usage=raw))
        if entry == "response"
        else M._extract_openai_stream_usage(raw)
    )
    assert asdict(usage) == {
        "prompt_tokens": 1000,
        "completion_tokens": 200,
        "total_tokens": 1200,
        "reasoning_tokens": reasoning,
        "cache_read_tokens": read,
        "cache_write_tokens": write,
        "cache_write_1h_tokens": 0,
        "cache_fields_seen": seen,
    }


@pytest.mark.parametrize("entry", ["response", "stream-fallback", "stream-final"])
@pytest.mark.parametrize(
    "details,prompt,read,write,write_1h,seen",
    [
        ({}, 300, 0, 0, 0, False),
        (
            {"cache_read_input_tokens": 2000, "cache_creation_input_tokens": 500},
            2800,
            2000,
            500,
            0,
            True,
        ),
        (
            {
                "cache_read_input_tokens": 2000,
                "cache_creation_input_tokens": 500,
                "cache_creation": NS(ephemeral_5m_input_tokens=200, ephemeral_1h_input_tokens=300),
            },
            2800,
            2000,
            500,
            300,
            True,
        ),
    ],
    ids=["missing", "cache-total", "ttl-breakdown"],
)
def test_anthropic_token_accounting(entry, details, prompt, read, write, write_1h, seen):
    raw = NS(input_tokens=300, output_tokens=200, **details)
    mixin = M()
    if entry == "response":
        usage = mixin._extract_anthropic_usage(NS(usage=raw))
    elif entry == "stream-fallback":
        usage = mixin._extract_anthropic_stream_usage(NS(), raw)
    else:
        usage = mixin._extract_anthropic_stream_usage(
            NS(final_message=NS(usage=raw)), NS(input_tokens=999, output_tokens=888)
        )
    assert asdict(usage) == {
        "prompt_tokens": prompt,
        "completion_tokens": 200,
        "total_tokens": prompt + 200,
        "reasoning_tokens": 0,
        "cache_read_tokens": read,
        "cache_write_tokens": write,
        "cache_write_1h_tokens": write_1h,
        "cache_fields_seen": seen,
    }


def test_absent_usage_is_distinct_from_a_zero_token_record():
    assert M._extract_openai_usage(NS()) is None
    assert M._extract_openai_stream_usage(None) is None
    assert M._extract_anthropic_usage(NS()) is None
    assert M()._extract_anthropic_stream_usage(NS(), None) is None


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


def test_anthropic_1h_cache_write_bills_at_2x_input() -> None:
    """A 1h cache write costs 2x base input; a 5m write costs 1.25x.

    claude-sonnet-4-6: input 3.0/M, 5m write 3.75/M, 1h write 6.0/M (2x input).
    """
    write_5m, currency = calculate_chat_cost(
        provider="anthropic",
        model="claude-sonnet-4-6",
        prompt_tokens=1_000_000,
        completion_tokens=0,
        cache_write_tokens=1_000_000,
        cache_write_1h_tokens=0,
    )
    write_1h, _ = calculate_chat_cost(
        provider="anthropic",
        model="claude-sonnet-4-6",
        prompt_tokens=1_000_000,
        completion_tokens=0,
        cache_write_tokens=1_000_000,
        cache_write_1h_tokens=1_000_000,
    )
    assert currency == "USD"
    assert write_5m == pytest.approx(3.75)  # 5m rate from registry
    assert write_1h == pytest.approx(6.0)  # 2x input, not the 5m 3.75
    assert write_1h > write_5m


def test_mixed_5m_and_1h_writes_split_correctly() -> None:
    # 1M total writes, half 1h: 0.5M @ 6.0 + 0.5M @ 3.75 = 3.0 + 1.875 = 4.875
    amount, _ = calculate_chat_cost(
        provider="anthropic",
        model="claude-sonnet-4-6",
        prompt_tokens=1_000_000,
        completion_tokens=0,
        cache_write_tokens=1_000_000,
        cache_write_1h_tokens=500_000,
    )
    assert amount == pytest.approx(0.5 * 6.0 + 0.5 * 3.75)
