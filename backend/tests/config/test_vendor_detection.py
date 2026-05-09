"""Tests for ModelVendor heuristic detection used by custom-gateway models."""

from __future__ import annotations

import pytest

from magi.config.models import ModelVendor
from magi.config.vendor_detection import detect_vendor_from_hints


@pytest.mark.parametrize(
    "model_id,expected",
    [
        # GLM family
        ("glm-4-plus", ModelVendor.GLM),
        ("glm-4.5", ModelVendor.GLM),
        ("chatglm3-6b", ModelVendor.GLM),
        ("codegeex4", ModelVendor.GLM),
        # DashScope / Qwen
        ("qwen-max", ModelVendor.DASHSCOPE),
        ("qwen3-coder", ModelVendor.DASHSCOPE),
        ("qwq-32b-preview", ModelVendor.DASHSCOPE),
        ("qvq-72b-preview", ModelVendor.DASHSCOPE),
        # Anthropic family
        ("claude-3-opus", ModelVendor.ANTHROPIC),
        ("claude-sonnet-4-6", ModelVendor.ANTHROPIC),
        # Grok
        ("grok-2", ModelVendor.GROK),
        ("grok-beta", ModelVendor.GROK),
        # OpenAI family + DeepSeek (intentionally OPENAI vendor)
        ("gpt-4o-mini", ModelVendor.OPENAI),
        ("gpt-5", ModelVendor.OPENAI),
        ("o1-preview", ModelVendor.OPENAI),
        ("o3-mini", ModelVendor.OPENAI),
        ("o4-mini", ModelVendor.OPENAI),
        ("deepseek-chat", ModelVendor.OPENAI),
        ("deepseek-reasoner", ModelVendor.OPENAI),
        # Unknown
        ("totally-mystery-model", ModelVendor.GENERIC),
        ("", ModelVendor.GENERIC),
    ],
)
def test_detect_vendor_by_model_id(model_id: str, expected: ModelVendor) -> None:
    assert detect_vendor_from_hints(model_id=model_id) == expected


def test_model_id_overrides_url_when_both_present() -> None:
    """OneAPI / NewAPI: same URL, multiple vendors. Model id must win."""
    one_api_url = "https://oneapi.example.com/v1"
    assert (
        detect_vendor_from_hints(model_id="qwen-max", base_url=one_api_url)
        == ModelVendor.DASHSCOPE
    )
    assert (
        detect_vendor_from_hints(model_id="glm-4-plus", base_url=one_api_url)
        == ModelVendor.GLM
    )
    assert (
        detect_vendor_from_hints(model_id="claude-3-opus", base_url=one_api_url)
        == ModelVendor.ANTHROPIC
    )
    assert (
        detect_vendor_from_hints(model_id="gpt-4o", base_url=one_api_url)
        == ModelVendor.OPENAI
    )


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://api.openai.com/v1", ModelVendor.OPENAI),
        ("https://api.anthropic.com/v1", ModelVendor.ANTHROPIC),
        ("https://open.bigmodel.cn/api/paas/v4", ModelVendor.GLM),
        ("https://dashscope.aliyuncs.com/compatible-mode/v1", ModelVendor.DASHSCOPE),
        ("https://api.x.ai/v1", ModelVendor.GROK),
        ("https://api.deepseek.com/v1", ModelVendor.OPENAI),
    ],
)
def test_detect_vendor_falls_back_to_url_when_model_id_unknown(
    url: str, expected: ModelVendor
) -> None:
    """When the model id has no marker, the base URL is consulted."""
    assert (
        detect_vendor_from_hints(model_id="some-relabel", base_url=url) == expected
    )


def test_no_signals_returns_generic() -> None:
    assert detect_vendor_from_hints(model_id=None, base_url=None) == ModelVendor.GENERIC
    assert detect_vendor_from_hints(model_id="", base_url="") == ModelVendor.GENERIC
