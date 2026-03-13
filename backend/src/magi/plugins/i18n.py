"""
Plugin Internationalization Module.

Provides i18n support for plugins with per-plugin translation files.

Usage in plugins:
    self.t("summary.played_track", track_name="Song", duration=30)
    # With fallback: self.t("key", fallback="Default text", **kwargs)

Translation file structure (plugins/<plugin_id>/i18n/zh-CN.json):
    {
        "summary": {
            "played_track": "播放了 {track_name} ({duration}秒)",
            "visited_page": "访问了 {title} ({count}次)"
        },
        "content": {
            "repo": "仓库：{path}",
            "operation": "操作：{type}"
        }
    }
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default language when not specified
DEFAULT_LANGUAGE = "en"

# Supported language codes mapping (normalizes variations)
LANGUAGE_ALIASES = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh_CN": "zh-CN",
    "zh_CN.UTF-8": "zh-CN",
    "en": "en",
    "en-us": "en",
    "en_US": "en",
}


class PluginI18n:
    """
    Internationalization helper for plugins.

    Loads translations from the plugin's i18n/ directory and provides
    a simple t() method for looking up translations with fallback.
    """

    def __init__(self, plugin_id: str, plugin_dir: Path):
        """
        Initialize the i18n helper.

        Args:
            plugin_id: The plugin's unique identifier
            plugin_dir: Path to the plugin's root directory
        """
        self.plugin_id = plugin_id
        self.plugin_dir = plugin_dir
        self.i18n_dir = plugin_dir / "i18n"
        self._translations: Dict[str, Dict[str, Any]] = {}
        self._loaded_languages: set[str] = set()

    def _normalize_language(self, lang: Optional[str]) -> str:
        """Normalize language code to standard format."""
        if not lang:
            return DEFAULT_LANGUAGE

        lang_lower = lang.lower()
        return LANGUAGE_ALIASES.get(lang_lower, LANGUAGE_ALIASES.get(lang, lang))

    def _load_translations(self, language: str) -> Dict[str, Any]:
        """
        Load translations for a specific language.

        Args:
            language: Language code (e.g., "zh-CN", "en")

        Returns:
            Translation dictionary, empty dict if file not found
        """
        normalized = self._normalize_language(language)

        if normalized in self._loaded_languages:
            return self._translations.get(normalized, {})

        # Try to load the translation file
        lang_file = self.i18n_dir / f"{normalized}.json"

        if not lang_file.exists():
            # Fall back to default language if requested language not found
            if normalized != DEFAULT_LANGUAGE:
                logger.debug(
                    f"Translation file not found for {self.plugin_id}/{normalized}, "
                    f"falling back to {DEFAULT_LANGUAGE}"
                )
                return self._load_translations(DEFAULT_LANGUAGE)
            return {}

        try:
            with open(lang_file, "r", encoding="utf-8") as f:
                translations = json.load(f)
            self._translations[normalized] = translations
            self._loaded_languages.add(normalized)
            logger.debug(f"Loaded translations for {self.plugin_id}/{normalized}")
            return translations
        except Exception as e:
            logger.error(f"Failed to load translations for {self.plugin_id}/{normalized}: {e}")
            return {}

    def t(
        self,
        key: str,
        language: Optional[str] = None,
        fallback: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Get a translated string with optional interpolation.

        Args:
            key: Translation key (dot-notation, e.g., "summary.played_track")
            language: Target language code (defaults to DEFAULT_LANGUAGE)
            fallback: Fallback string if translation not found
            **kwargs: Variables for string interpolation

        Returns:
            Translated and interpolated string
        """
        translations = self._load_translations(language)

        # Navigate the nested dictionary using dot notation
        value = self._get_nested(translations, key)

        if value is None:
            if fallback is not None:
                return self._interpolate(fallback, **kwargs)
            # Return the key itself as last resort
            return key

        if not isinstance(value, str):
            # If the value isn't a string, convert to string
            value = str(value)

        return self._interpolate(value, **kwargs)

    def _get_nested(self, data: Dict[str, Any], key: str) -> Any:
        """Get a nested value using dot notation."""
        parts = key.split(".")
        current = data

        for part in parts:
            if not isinstance(current, dict):
                return None
            current = current.get(part)

        return current

    def _interpolate(self, template: str, **kwargs: Any) -> str:
        """
        Interpolate variables into a template string.

        Supports both {var} and {{var}} style placeholders.
        """
        if not kwargs:
            return template

        try:
            # Use Python's format for {var} style
            return template.format(**kwargs)
        except KeyError:
            # If some keys are missing, return the template as-is
            return template

    def get_available_languages(self) -> list[str]:
        """Get list of available language codes for this plugin."""
        if not self.i18n_dir.exists():
            return [DEFAULT_LANGUAGE]

        languages = []
        for lang_file in self.i18n_dir.glob("*.json"):
            languages.append(lang_file.stem)

        return languages if languages else [DEFAULT_LANGUAGE]

    def reload(self) -> None:
        """Clear cached translations, forcing reload on next access."""
        self._translations.clear()
        self._loaded_languages.clear()


# Thread-local storage for current request language
import threading

_current_language = threading.local()


def set_current_language(language: Optional[str]) -> None:
    """
    Set the current thread's language context.

    This should be called at the beginning of a request or task
    to establish the language preference for all plugin operations.
    """
    _current_language.value = language


def get_current_language() -> str:
    """
    Get the current thread's language context.

    Returns DEFAULT_LANGUAGE if no context is set.
    """
    return getattr(_current_language, "value", DEFAULT_LANGUAGE)
