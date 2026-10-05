from __future__ import annotations

import pytest

from magi.i18n import (
    app_language_code,
    effective_app_language_code,
    get_effective_language,
    is_effective_zh_language,
    is_zh_language,
    language_context,
    language_family,
    llm_language_label,
    normalize_language,
    t,
)


@pytest.mark.parametrize(
    ("raw", "normalized", "family", "app_code"),
    [
        ("zh-CN,zh;q=0.9", "zh-CN", "zh", "zh"),
        ("zh_Hans", "zh-CN", "zh", "zh"),
        ("en-US,en;q=0.8", "en", "en", "en"),
        (None, "zh-CN", "zh", "zh"),
        ("ja-JP", "ja-JP", "ja", "en"),
    ],
)
def test_language_normalization_and_supported_app_fallback(raw, normalized, family, app_code):
    assert normalize_language(raw) == normalized
    assert language_family(raw) == family
    assert is_zh_language(raw) is (family == "zh")
    assert app_language_code(raw) == app_code


def test_translate_uses_context_language() -> None:
    with language_context("en-US"):
        assert "does not support image input" in t("chat.image_vision_unsupported")

    with language_context("zh"):
        assert "当前核心模型不支持图片输入" in t("chat.image_vision_unsupported")


def test_translate_falls_back_to_english_catalog_for_unknown_locale() -> None:
    with language_context("ja"):
        assert "does not support image input" in t("chat.image_vision_unsupported")


def test_effective_language_helpers_use_context_language() -> None:
    with language_context("zh"):
        assert is_effective_zh_language(default="en") is True
        assert effective_app_language_code(default="en") == "zh"
        assert llm_language_label(default="en") == "Simplified Chinese (zh-CN)"

    with language_context("en"):
        assert is_effective_zh_language(default="zh-CN") is False
        assert effective_app_language_code(default="zh-CN") == "en"
        assert llm_language_label(default="zh-CN") == "English"


def test_translate_uses_explicit_fallback_and_interpolation() -> None:
    assert t("missing.key", fallback="Hello {name}", language="en", name="Magi") == "Hello Magi"


def test_language_context_restores_previous_value() -> None:
    with language_context("en"):
        assert get_effective_language() == "en"
        with language_context("zh"):
            assert get_effective_language() == "zh-CN"
        assert get_effective_language() == "en"
