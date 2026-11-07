"""Media prices use provider counters and their published billing units."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.config.pricing_models import LLMModelCostModel
from magi.runtime_trace.media_usage import openai_media_usage, gemini_image_usage
from magi.llm.pricing import calculate_image_generation_cost, calculate_audio_cost
from magi.llm.subscribers.llm_usage_subscriber import LLMUsageSubscriber


def test_image_text_and_image_tokens_are_not_priced_as_a_flat_image_count():
    usage = openai_media_usage({'input_tokens': 100, 'output_tokens': 1000,
                               'input_tokens_details': {'text_tokens': 80, 'image_tokens': 20}}, output_modality='image')
    amount, currency = calculate_image_generation_cost(provider='openai', model='gpt-image-2.6-sunburst',
                                                       image_count=1, usage=usage)
    assert currency == 'USD'
    assert amount == pytest.approx((80 * 5 + 20 * 8 + 1000 * 30) / 1e6)
    assert calculate_image_generation_cost(provider='openai', model='gpt-image-2.6-sunburst', image_count=1) == (None, None)


def test_gemini_separate_thoughts_are_charged_once_as_text():
    usage = gemini_image_usage({'total_input_tokens': 100, 'total_output_tokens': 1140, 'total_thought_tokens': 30,
        'input_tokens_by_modality': [{'modality': 'text', 'tokens': 50}, {'modality': 'image', 'tokens': 50}],
        'output_tokens_by_modality': [{'modality': 'text', 'tokens': 20}, {'modality': 'image', 'tokens': 1120}]})
    assert usage['output_tokens'] == 1170
    assert usage['text_output_tokens'] == 50
    assert calculate_image_generation_cost(provider='gemini', model='gemini-nano-banana-2.1', image_count=1,
                                           usage=usage)[0] == pytest.approx(.034125)


@pytest.mark.parametrize('host,size,expected', [
    ('dashscope.aliyuncs.com', '1024x1024', .25), ('dashscope.aliyuncs.com', '2048x2048', .5),
    ('dashscope-intl.aliyuncs.com', '1024x1024', .299768), ('dashscope-intl.aliyuncs.com', '2048x2048', .562065),
])
def test_image_size_and_region_choose_published_price(host, size, expected):
    amount, currency = calculate_image_generation_cost(provider='dashscope', model='qwen-image-3.0-pro',
                                                       image_count=2, image_size=size, endpoint_host=host)
    assert currency == 'CNY'
    assert amount == pytest.approx(expected * 2)


def test_china_image_prices_do_not_inherit_international_currency():
    assert calculate_image_generation_cost(provider='glm', model='glm-image', image_count=2) == (.2, 'CNY')
    assert calculate_image_generation_cost(provider='minimax', model='image-01', image_count=2,
                                           endpoint_host='api.minimax.io') == (.007, 'USD')


def test_realtime_cached_text_and_audio_are_exclusive_buckets():
    usage = openai_media_usage({'input_tokens': 120, 'output_tokens': 110,
        'input_token_details': {'text_tokens': 100, 'audio_tokens': 20, 'cached_tokens': 55,
                               'cached_tokens_details': {'text_tokens': 50, 'audio_tokens': 5}},
        'output_token_details': {'text_tokens': 10, 'audio_tokens': 100}}, output_modality='audio')
    assert calculate_audio_cost(provider='openai', model='gpt-realtime-2.1-mini', usage=usage,
                                endpoint_host='api.openai.com')[0] == pytest.approx(.0022085)


@pytest.mark.parametrize('provider,model,host,count,amount,currency', [
    ('openai', 'tts-1', 'api.openai.com', 1000, .015, 'USD'),
    ('minimax', 'speech-2.8-hd', 'api.minimaxi.com', 1000, .35, 'CNY'),
    ('minimax', 'speech-2.8-hd', 'api.minimax.io', 1000, .1, 'USD'),
    ('dashscope', 'qwen-audio-3.1-tts-plus', 'test.cn-beijing.maas.aliyuncs.com', 1000, .14, 'CNY'),
    ('dashscope', 'qwen-audio-3.1-tts-plus', 'test.ap-southeast-1.maas.aliyuncs.com', 1000, .219, 'CNY'),
])
def test_speech_character_prices(provider, model, host, count, amount, currency):
    result, code = calculate_audio_cost(provider=provider, model=model, characters=count, endpoint_host=host)
    assert result == pytest.approx(amount)
    assert code == currency


def test_speech_token_prices_and_unknown_usage():
    usage = {'input_tokens': 1000, 'text_input_tokens': 1000, 'output_tokens': 100, 'audio_output_tokens': 100}
    assert calculate_audio_cost(provider='dashscope', model='qwen-audio-3.1-tts-flash', usage=usage,
                                endpoint_host='test.ap-southeast-1.maas.aliyuncs.com')[0] == pytest.approx(.0030406)
    assert calculate_audio_cost(provider='openai', model='gpt-4o-mini-tts', endpoint_host='api.openai.com') == (None, None)
    usage['audio_output_tokens'] = 99
    assert calculate_audio_cost(provider='dashscope', model='qwen-audio-3.1-tts-flash', usage=usage,
                                endpoint_host='test.cn-beijing.maas.aliyuncs.com') == (None, None)


@pytest.mark.parametrize('raw', [None, {}, {'input_tokens': 'bad'}, {'input_tokens': 1, 'output_tokens': 1,
    'input_tokens_details': {'text_tokens': 1, 'cached_tokens': 1}}])
def test_invalid_or_unsplit_cache_usage_is_not_fabricated(raw):
    assert openai_media_usage(raw, output_modality='image') is None


def test_custom_image_price_is_not_accidentally_routed_to_chat_token_pricing():
    sub = LLMUsageSubscriber(event_bus=MagicMock(), llm_usage_store=MagicMock())
    attrs = {'request_kind': 'image_generation', 'usage_available': True, 'image_count': 1,
             'cost_override': {'currency': 'CNY', 'input_per_million_tokens': 3, 'image_output_per_million_tokens': 10},
             'billing': {'media_usage': {'input_tokens': 100, 'text_input_tokens': 100,
                                          'output_tokens': 1000, 'image_output_tokens': 1000}}}
    amount, currency = sub._resolve_cost(attrs=attrs, payload=SimpleNamespace(name='image', started_at_ms=1000),
                                        provider='custom', model='image', prompt_tokens=100, completion_tokens=1000)
    assert amount == pytest.approx(.0103)
    assert currency == 'CNY'


def test_resolution_dependent_price_requires_actual_resolution():
    assert calculate_image_generation_cost(provider='dashscope', model='qwen-image-3.0-pro', image_count=1) == (None, None)


@pytest.mark.asyncio
async def test_image_factory_preserves_instance_override_and_actual_endpoint():
    from magi.config.models import LLMProviderSettings, LLMModelMetadataOverrideSettings
    from magi.llm.pricing import _load_provider_registry
    from magi.llm.image_generation.factory import create_image_generation_adapter

    settings = LLMProviderSettings(provider_type='openai', api_key='private-key',
        model_metadata_overrides={'gpt-image-2.6-sunburst': LLMModelMetadataOverrideSettings(
            cost=LLMModelCostModel(currency='CNY', per_image=2))})
    settings.services.image_generation.enabled = True
    adapter = create_image_generation_adapter(provider_id='my-account', provider_settings=settings,
        model='gpt-image-2.6-sunburst', registry=_load_provider_registry(), timeout=10)
    try:
        assert adapter.billing_context['provider'] == 'openai'
        assert adapter.billing_context['endpoint_host'] == 'api.openai.com'
        assert adapter.billing_context['cost_override']['per_image'] == 2
        assert 'private-key' not in str(adapter.billing_context)
    finally:
        await adapter.aclose()
