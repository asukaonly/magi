"""Published price boundaries and exclusive cache billing buckets."""
from datetime import datetime

import pytest
from pydantic import ValidationError

from magi.config.pricing_models import LLMModelCostModel, LLMPricingRule, LLMPeakPricing
from magi.llm.pricing import calculate_chat_cost


def price(provider, model, prompt=1000, output=100, **kwargs):
    return calculate_chat_cost(provider=provider, model=model, prompt_tokens=prompt,
                               completion_tokens=output, **kwargs)


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


@pytest.mark.parametrize('provider,model,threshold,low,high', [
    ('openai', 'gpt-6.1-sol', 272001, 2, 4),
    ('anthropic', 'claude-haiku-5-5', 100001, .1, .5),
    ('glm', 'glm-5.1', 32000, 6, 8),
    ('gemini', 'gemini-3.1-pro-preview', 200001, 2, 4),
    ('grok', 'grok-4.7', 200000, 2, 4),
    ('dashscope', 'qwen3.7-plus', 256001, 2, 6),
    ('dashscope', 'qwen3.5-plus', 128001, .8, 2),
    ('minimax', 'MiniMax-M3', 512001, 2.1, 4.2),
])
def test_input_tier_prices_the_whole_request(provider, model, threshold, low, high):
    assert price(provider, model, threshold - 1, 0)[0] == pytest.approx((threshold - 1) * low / 1e6)
    assert price(provider, model, threshold, 0)[0] == pytest.approx(threshold * high / 1e6)


def test_total_input_including_cache_selects_tier_and_output_rate():
    assert price('anthropic', 'claude-haiku-5-5', 100001, 1000,
                 cache_read_tokens=100001)[0] == pytest.approx((100001 * .05 + 1000 * 2.5) / 1e6)
    assert price('glm', 'glm-4.7', 1000, 199)[0] == pytest.approx((1000 * 2 + 199 * 8) / 1e6)
    assert price('glm', 'glm-4.7', 1000, 200)[0] == pytest.approx((1000 * 3 + 200 * 14) / 1e6)


def test_mixed_cache_buckets_replace_input_instead_of_adding_to_it():
    # 100 ordinary + 200 hits + 300 short writes + 400 long writes = 1000 input.
    assert price('openai', 'gpt-6.1-sol', cache_read_tokens=200,
                 cache_write_tokens=700, cache_write_12h_tokens=400)[0] == pytest.approx(
                     (100 * 2 + 200 * .1 + 300 * 2.5 + 400 * 5 + 100 * 10) / 1e6)
    assert price('kimi', 'kimi-k3.1-pro', 1000, 0, cache_write_tokens=1000,
                 cache_write_1h_tokens=1000)[0] == pytest.approx(.026)


@pytest.mark.parametrize('model,implicit,explicit,write', [
    ('qwen3.8-max', 1.5, 1, 15), ('qwen3.8-flash', .1, .1, 1.25),
])
def test_explicit_cache_exception_rates(model, implicit, explicit, write):
    assert price('dashscope', model, 1000, 0, cache_read_tokens=1000)[0] == pytest.approx(implicit / 1000)
    assert price('dashscope', model, 1000, 0, cache_read_tokens=1000,
                 cache_mode='explicit')[0] == pytest.approx(explicit / 1000)
    assert price('dashscope', model, 1000, 0, cache_write_tokens=1000,
                 cache_mode='explicit')[0] == pytest.approx(write / 1000)


@pytest.mark.parametrize('at,multiplier', [
    ('2026-11-06T00:59:59Z', 1), ('2026-11-06T01:00:00Z', 2),
    ('2026-11-06T03:59:59Z', 2), ('2026-11-06T04:00:00Z', 1),
    ('2026-11-06T06:00:00Z', 2), ('2026-11-06T10:00:00Z', 1),
    ('2026-11-07T02:00:00Z', 1), ('2026-10-01T02:00:00Z', 1),
    ('2028-01-08T02:00:00Z', 1), ('2027-02-08T02:00:00Z', 1), ('2027-02-15T02:00:00Z', 2),
])
def test_peak_utc_boundaries_weekends_and_published_holidays(at, multiplier):
    assert price('deepseek', 'deepseek-flash', requested_at=timestamp(at))[0] == pytest.approx(.00021 * multiplier)


def test_calendar_and_promotion_expiry_do_not_guess_unpublished_prices():
    assert price('deepseek', 'deepseek-flash', requested_at=timestamp('2028-01-05T02:00:00Z')) == (None, None)
    assert price('openai', 'gpt-5.6', requested_at=timestamp('2026-11-30T23:59:59Z'))[0] is not None
    assert price('openai', 'gpt-5.6', requested_at=timestamp('2026-12-01T00:00:00Z')) == (None, None)
    assert price('gemini', 'gemini-3.8-flash', requested_at=timestamp('2026-12-31T23:59:59Z'))[0] == pytest.approx(.001125)
    assert price('gemini', 'gemini-3.8-flash', requested_at=timestamp('2027-01-01T00:00:00Z'))[0] == pytest.approx(.00225)


def test_regional_currency_and_speed_multipliers_compose():
    assert price('minimax', 'MiniMax-M3', 600000, 1000, endpoint_host='api.minimax.io',
                 service_tier='priority') == pytest.approx((.5436, 'USD'))
    amount, currency = price('openai', 'gpt-6.1-sol', 300000, 1000,
                             endpoint_host='eu.api.openai.com', service_tier='priority')
    assert currency == 'USD'
    assert amount == pytest.approx((300000 * 8 + 1000 * 30) / 1e6 * 1.1)
    assert price('dashscope', 'qwen3.8-flash', 1000, 0,
                 endpoint_host='dashscope-intl.aliyuncs.com') == (.001094, 'CNY')
    assert price('anthropic', 'claude-opus-5-5', 1000, 0,
                 inference_geo='us', service_tier='fast')[0] == pytest.approx(.0088)


@pytest.mark.parametrize('kwargs', [
    {'cache_read_tokens': 1001}, {'cache_write_tokens': 1001},
    {'cache_write_tokens': 500, 'cache_write_1h_tokens': 501},
    {'cache_read_tokens': -1}, {'requested_at': float('nan')},
    {'requested_at': 1e99}, {'endpoint_host': 'unverified.example'},
    {'service_tier': 'unknown'},
])
def test_invalid_or_unverified_usage_is_unknown(kwargs):
    assert price('openai', 'gpt-6.1-sol', **kwargs) == (None, None)


def test_missing_prices_are_not_free_and_custom_account_overrides_apply():
    assert price('glm', 'glm-4.7-flash') == (0, 'CNY')
    assert price('custom', 'new-model') == (None, None)
    cost = LLMModelCostModel(currency='CNY', input_per_million_tokens=2, output_per_million_tokens=4)
    assert price('custom', 'new-model', cost_override=cost) == (.0024, 'CNY')
    assert price('custom', 'new-model', cache_read_tokens=1, cost_override=cost) == (None, None)
    assert price('openai', 'gpt-5.2', cache_write_tokens=1) == (None, None)


def test_rule_patch_survives_full_config_roundtrip_and_preserves_explicit_null():
    cost = LLMModelCostModel.model_validate({'currency': 'CNY', 'input_per_million_tokens': 2,
        'output_per_million_tokens': 4, 'rules': [
            {'min_input_tokens': 100, 'rates': {'input_per_million_tokens': 3}},
            {'min_input_tokens': 2000, 'rates': {'input_per_million_tokens': None}},
        ]})
    copy = LLMModelCostModel.model_validate_json(cost.model_dump_json())
    assert price('custom', 'model', cost_override=copy) == (.0034, 'CNY')
    assert price('custom', 'model', 2000, 0, cost_override=copy) == (None, None)


@pytest.mark.parametrize('bad', [
    {'input_per_million_tokens': -1}, {'output_per_million_tokens': float('inf')},
    {'rules': [{'min_input_tokens': 5, 'max_input_tokens': 4}]},
    {'rules': [{'starts_at': '2026-01-01T00:00:00'}]},
    {'rules': [{'starts_at': '2026-02-01T00:00:00Z', 'ends_at': '2026-01-01T00:00:00Z'}]},
])
def test_invalid_price_configuration_is_rejected(bad):
    with pytest.raises(ValidationError):
        LLMModelCostModel.model_validate(bad)


def test_thinking_condition_does_not_guess_a_mode():
    cost = LLMModelCostModel(input_per_million_tokens=1, output_per_million_tokens=1,
                            rules=[LLMPricingRule(thinking=True, multiplier=2)])
    assert price('custom', 'model', cost_override=cost) == (None, None)
    assert price('custom', 'model', thinking=False, cost_override=cost)[0] == pytest.approx(.0011)
    assert price('custom', 'model', thinking=True, cost_override=cost)[0] == pytest.approx(.0022)


def test_peak_calendar_rejects_invalid_intervals():
    with pytest.raises(ValidationError):
        LLMPeakPricing(utc_windows=[(100, 0)], multiplier=2, calendar_years=[2026], holidays=[], sources=[])
