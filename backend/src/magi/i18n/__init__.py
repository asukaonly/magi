"""Core backend internationalization helpers."""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "zh-CN"
FALLBACK_LANGUAGE = "en"

LANGUAGE_ALIASES = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh_cn": "zh-CN",
    "zh_cn.utf-8": "zh-CN",
    "zh-hans": "zh-CN",
    "en": "en",
    "en-us": "en",
    "en_us": "en",
    "en-gb": "en",
    "en_gb": "en",
}

_LOCALE_DIR = Path(__file__).resolve().parent / "locales"
_current_language: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "magi_current_language",
    default=None,
)


def normalize_language(language: str | None, *, default: str = DEFAULT_LANGUAGE) -> str:
    """Normalize a user or request language code to a supported backend locale."""
    text = str(language or "").strip()
    if not text:
        return default

    primary = text.split(",", 1)[0].split(";", 1)[0].strip()
    if not primary:
        return default

    alias_key = primary.lower().replace("_", "-")
    if alias_key.startswith("zh"):
        return "zh-CN"
    if alias_key.startswith("en"):
        return "en"
    return LANGUAGE_ALIASES.get(alias_key, primary)


def language_family(language: str | None, *, default: str = DEFAULT_LANGUAGE) -> str:
    """Return the primary language family, such as ``zh`` or ``en``."""
    resolved = normalize_language(language, default=default)
    family = resolved.lower().replace("_", "-").split("-", 1)[0]
    if family:
        return family
    return normalize_language(default).lower().replace("_", "-").split("-", 1)[0]


def is_zh_language(language: str | None, *, default: str = DEFAULT_LANGUAGE) -> bool:
    """Return whether *language* resolves to a Chinese locale."""
    return language_family(language, default=default) == "zh"


def app_language_code(language: str | None, *, default: str = DEFAULT_LANGUAGE) -> str:
    """Return the app's supported language code for user-facing output."""
    return "zh" if is_zh_language(language, default=default) else "en"


def is_effective_zh_language(*, default: str = DEFAULT_LANGUAGE) -> bool:
    """Return whether the current effective language is Chinese."""
    return is_zh_language(get_effective_language(default=default), default=default)


def effective_app_language_code(*, default: str = DEFAULT_LANGUAGE) -> str:
    """Return the app language code for the current effective language."""
    return app_language_code(get_effective_language(default=default), default=default)


def llm_language_label(language: str | None = None, *, default: str = DEFAULT_LANGUAGE) -> str:
    """Return the target language label used in LLM instructions."""
    resolved = get_effective_language(default=default) if language is None else normalize_language(language, default=default)
    return "Simplified Chinese (zh-CN)" if is_zh_language(resolved, default=default) else "English"


def set_current_language(language: str | None) -> None:
    """Set the current async context language for backend i18n lookups."""
    _current_language.set(normalize_language(language) if language else None)


def get_current_language(default: str = DEFAULT_LANGUAGE) -> str:
    """Return the current async context language, or *default* if none is set."""
    return _current_language.get() or default


@contextlib.contextmanager
def language_context(language: str | None) -> Iterator[None]:
    """Temporarily set the backend i18n language in the current context."""
    token = _current_language.set(normalize_language(language) if language else None)
    try:
        yield
    finally:
        _current_language.reset(token)


def get_preferred_language(default: str = DEFAULT_LANGUAGE) -> str:
    """Return the configured user interface language when runtime config is available."""
    try:
        from ..config.loader import get_user_preference

        preferred = get_user_preference("language", None)
    except Exception:
        preferred = None
    return normalize_language(str(preferred), default=default) if preferred else default


def get_effective_language(
    language: str | None = None,
    *,
    default: str = DEFAULT_LANGUAGE,
) -> str:
    """Resolve explicit, context, and user-preference language sources."""
    if language:
        return normalize_language(language, default=default)
    current = _current_language.get()
    if current:
        return normalize_language(current, default=default)
    return get_preferred_language(default=default)


def t(
    key: str,
    *,
    fallback: str | None = None,
    language: str | None = None,
    **kwargs: Any,
) -> str:
    """Translate a backend user-facing string by dot-notated key."""
    resolved_language = get_effective_language(language)
    value = _lookup_catalog_value(resolved_language, key)
    if value is None and resolved_language != FALLBACK_LANGUAGE:
        value = _lookup_catalog_value(FALLBACK_LANGUAGE, key)
    if value is None:
        value = fallback if fallback is not None else key
    if not isinstance(value, str):
        value = str(value)
    return _interpolate(value, **kwargs)


def _lookup_catalog_value(language: str, key: str) -> Any:
    catalog = _load_catalog(normalize_language(language))
    current: Any = catalog
    for part in key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


@lru_cache(maxsize=None)
def _load_catalog(language: str) -> dict[str, Any]:
    locale_path = _LOCALE_DIR / f"{normalize_language(language)}.json"
    if not locale_path.exists():
        return {}
    try:
        with locale_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        logger.warning("Failed to load i18n catalog %s: %s", locale_path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _interpolate(template: str, **kwargs: Any) -> str:
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        return template
