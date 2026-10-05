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
        # Gemini
        ("gemini-2.5-pro", ModelVendor.GEMINI),
        ("gemini-3-flash", ModelVendor.GEMINI),
        # Kimi / Moonshot
        ("kimi-k2.6", ModelVendor.KIMI),
        ("moonshot-v1-8k", ModelVendor.KIMI),
        # MiniMax
        ("minimax-m2", ModelVendor.MINIMAX),
        ("abab6.5-chat", ModelVendor.MINIMAX),
        # DeepSeek family
        ("deepseek-chat", ModelVendor.DEEPSEEK),
        ("deepseek-reasoner", ModelVendor.DEEPSEEK),
        # OpenAI family
        ("gpt-4o-mini", ModelVendor.OPENAI),
        ("gpt-5", ModelVendor.OPENAI),
        ("o1-preview", ModelVendor.OPENAI),
        ("o3-mini", ModelVendor.OPENAI),
        ("o4-mini", ModelVendor.OPENAI),
        # Unknown
        ("totally-mystery-model", ModelVendor.GENERIC),
        ("", ModelVendor.GENERIC),
        (None, ModelVendor.GENERIC),
    ],
)
def test_detect_vendor_by_model_id(
    model_id: str | None, expected: ModelVendor
) -> None:
    assert detect_vendor_from_hints(model_id=model_id) == expected


@pytest.mark.parametrize(
    "model_id,model_vendor,base_url,url_vendor",
    [
        ("qwen-max", ModelVendor.DASHSCOPE, "https://api.openai.com/v1", ModelVendor.OPENAI),
        ("glm-4-plus", ModelVendor.GLM, "https://api.anthropic.com/v1", ModelVendor.ANTHROPIC),
        (
            "claude-3-opus",
            ModelVendor.ANTHROPIC,
            "https://api.deepseek.com/v1",
            ModelVendor.DEEPSEEK,
        ),
        (
            "gpt-4o",
            ModelVendor.OPENAI,
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ModelVendor.DASHSCOPE,
        ),
    ],
)
def test_recognized_model_overrides_conflicting_vendor_url(
    model_id, model_vendor, base_url, url_vendor
):
    assert detect_vendor_from_hints(model_id=None, base_url=base_url) == url_vendor
    assert detect_vendor_from_hints(model_id=model_id, base_url=base_url) == model_vendor


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://api.openai.com/v1", ModelVendor.OPENAI),
        ("https://api.anthropic.com/v1", ModelVendor.ANTHROPIC),
        ("https://open.bigmodel.cn/api/paas/v4", ModelVendor.GLM),
        ("https://dashscope.aliyuncs.com/compatible-mode/v1", ModelVendor.DASHSCOPE),
        ("https://api.x.ai/v1", ModelVendor.GROK),
        ("https://api.deepseek.com/v1", ModelVendor.DEEPSEEK),
        ("https://generativelanguage.googleapis.com/v1beta", ModelVendor.GEMINI),
        ("https://api.moonshot.cn/v1", ModelVendor.KIMI),
        ("https://api.minimax.chat/v1", ModelVendor.MINIMAX),
    ],
)
def test_detect_vendor_falls_back_to_url_when_model_id_unknown(
    url: str, expected: ModelVendor
) -> None:
    """When the model id has no marker, the base URL is consulted."""
    assert (
        detect_vendor_from_hints(model_id="some-relabel", base_url=url) == expected
    )


@pytest.mark.parametrize("model_id,base_url", [(None,None),("",""),("unrecognized","https://unknown.example/v1")])
def test_unrecognized_or_absent_hints_keep_generic_vendor(model_id,base_url):
    assert detect_vendor_from_hints(model_id=model_id,base_url=base_url) == ModelVendor.GENERIC
