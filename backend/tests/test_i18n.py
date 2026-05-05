from __future__ import annotations

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


def test_normalize_language_handles_headers_and_aliases() -> None:
    assert normalize_language("zh-CN,zh;q=0.9") == "zh-CN"
    assert normalize_language("zh_Hans") == "zh-CN"
    assert normalize_language("en-US,en;q=0.8") == "en"
    assert normalize_language(None) == "zh-CN"


def test_translate_uses_context_language() -> None:
    with language_context("en-US"):
        assert "does not support image input" in t("chat.image_vision_unsupported")

    with language_context("zh"):
        assert "当前核心模型不支持图片输入" in t("chat.image_vision_unsupported")


def test_translate_falls_back_to_english_catalog_for_unknown_locale() -> None:
    with language_context("ja"):
        assert "does not support image input" in t("chat.image_vision_unsupported")


def test_language_helpers_normalize_families_and_supported_app_codes() -> None:
    assert language_family("zh-Hans") == "zh"
    assert language_family("en-US") == "en"
    assert language_family("ja-JP") == "ja"
    assert is_zh_language("zh-CN") is True
    assert is_zh_language("en") is False
    assert app_language_code("zh-CN") == "zh"
    assert app_language_code("ja-JP") == "en"


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