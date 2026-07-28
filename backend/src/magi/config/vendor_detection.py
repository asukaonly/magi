"""Heuristic ModelVendor inference for custom/manual models.

This is a *fallback* used only when neither the packaged registry nor
the user override declares a vendor. The intent is to give OneAPI /
NewAPI gateway users a sensible default; once the user (or a one-time
config migration) writes the vendor explicitly, this code path is no
longer consulted for that model.

Detection priority intentionally weights the model id heavily over the
base URL: a single OneAPI gateway routinely proxies models from many
vendors under the same URL, so routing off the URL would misclassify
most of them.
"""

from __future__ import annotations


from .models import ModelVendor


# (vendor, model-id substrings, base-url substrings)
_VENDOR_HINTS: tuple[tuple[ModelVendor, tuple[str, ...], tuple[str, ...]], ...] = (
    # GLM model families. Bigmodel.cn is Zhipu's official endpoint;
    # codeplan and z.ai are gateways for the same model family.
    (
        ModelVendor.GLM,
        ("glm-", "glm4", "glm_", "chatglm", "codegeex"),
        ("bigmodel.cn", "z.ai", "codeplan"),
    ),
    # Alibaba DashScope / Bailian. Note: Bailian can proxy non-Qwen
    # models too (the URL alone is not authoritative for vendor), so
    # we still rely on the model id when present.
    (
        ModelVendor.DASHSCOPE,
        ("qwen", "qwq", "qvq"),
        ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"),
    ),
    # Anthropic Claude family. Anthropic-native traffic does not flow
    # through this code path (it uses the Anthropic adapter), but
    # OneAPI gateways often expose claude-* models on an OpenAI-shape
    # endpoint, in which case vendor=anthropic still drives the right
    # reasoning dialect.
    (
        ModelVendor.ANTHROPIC,
        ("claude-",),
        ("api.anthropic.com",),
    ),
    # xAI Grok.
    (
        ModelVendor.GROK,
        ("grok-", "grok_"),
        ("api.x.ai", "x.ai"),
    ),
    # Google Gemini. OneAPI gateways often expose gemini-* on an
    # OpenAI-shape endpoint; generativelanguage is Google's native host.
    (
        ModelVendor.GEMINI,
        ("gemini",),
        ("generativelanguage",),
    ),
    # Moonshot Kimi. Markers cover both the model family name and the
    # Moonshot platform branding.
    (
        ModelVendor.KIMI,
        ("kimi", "moonshot"),
        ("moonshot",),
    ),
    # MiniMax. abab is MiniMax's legacy model-family prefix.
    (
        ModelVendor.MINIMAX,
        ("minimax", "abab"),
        ("minimax",),
    ),
    # DeepSeek family. Its transport is OpenAI-compatible, but the
    # thinking controls are vendor-specific (extra_body.thinking +
    # reasoning_effort), so it needs its own vendor classification.
    (
        ModelVendor.DEEPSEEK,
        ("deepseek",),
        ("api.deepseek.com",),
    ),
    # OpenAI family.
    (
        ModelVendor.OPENAI,
        ("gpt-", "o1-", "o3-", "o4-"),
        ("api.openai.com",),
    ),
)


def detect_vendor_from_hints(
    *,
    model_id: str | None,
    base_url: str | None = None,
) -> ModelVendor:
    """Infer ``ModelVendor`` from a model id and optional base URL.

    Returns :class:`ModelVendor.GENERIC` when no rule matches. Callers
    should treat the result as a *suggestion*; they remain free to
    override it via configuration.
    """
    needle_model = (model_id or "").strip().lower()
    needle_url = (base_url or "").strip().lower()

    # Pass 1: model-id markers (authoritative for OneAPI-style gateways).
    if needle_model:
        for vendor, model_markers, _ in _VENDOR_HINTS:
            for marker in model_markers:
                if marker in needle_model:
                    return vendor

    # Pass 2: base-url markers (only when model id was inconclusive).
    if needle_url:
        for vendor, _, url_markers in _VENDOR_HINTS:
            for marker in url_markers:
                if marker in needle_url:
                    return vendor

    return ModelVendor.GENERIC


__all__ = ["detect_vendor_from_hints"]
