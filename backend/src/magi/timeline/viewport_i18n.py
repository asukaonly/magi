"""Locale helpers shared by timeline viewport presentation builders."""

from __future__ import annotations

from typing import Any

from .. import i18n as core_i18n


def normalize_locale(locale: str | None) -> str:
    return "zh-CN" if core_i18n.is_zh_language(locale, default="en") else "en"


def is_zh_locale(locale: str | None) -> bool:
    return core_i18n.is_zh_language(locale, default="en")


def timeline_t(key: str, locale: str | None, *, fallback: str, **kwargs: Any) -> str:
    return core_i18n.t(f"timeline.{key}", language=locale, fallback=fallback, **kwargs)


def source_label(source_type: Any, locale: str) -> str:
    source = str(source_type or "memory")
    fallback = (
        source.replace("_", " ") if is_zh_locale(locale) else source.replace("_", " ").title()
    )
    return timeline_t(f"sources.{source}", locale, fallback=fallback)


def humanize_label(value: Any, *, locale: str = "en") -> str:
    text = str(value or "").replace("_", " ").replace("-", " ").strip()
    if not text:
        return timeline_t(
            "state.unknown",
            locale,
            fallback="未知" if is_zh_locale(locale) else "Unknown",
        )
    if is_zh_locale(locale):
        return timeline_t(f"mood.{text.lower()}", locale, fallback=text)
    return timeline_t(f"mood.{text.lower()}", locale, fallback=text.title())
