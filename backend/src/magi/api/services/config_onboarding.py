"""Onboarding configuration assembly helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ...core.logger import get_logger
from ...i18n import language_family
from ...utils.packaged_paths import get_backend_root
from ..routers.config_schemas import (
    FullPersonalityConfigModel,
    SystemConfigModel,
)

logger = get_logger(__name__)

QUICK_MODE_PERSONALITY_SEEDS: dict[str, dict[str, str]] = {
    "chat_assistant": {
        "zh": "echo",
        "en": "nova",
    },
    "life_monitor": {
        "zh": "sumen",
        "en": "ember",
    },
    "knowledge_partner": {
        "zh": "sichen",
        "en": "halberd",
    },
    "default": {
        "zh": "echo",
        "en": "nova",
    },
}


def read_onboarding_completed(config_path: Path) -> bool:
    """Read onboarding completion without masking persisted config errors."""
    if not config_path.exists():
        return False

    with config_path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file)

    if payload is None:
        raise ValueError("Persisted configuration is empty")
    if not isinstance(payload, dict):
        raise ValueError("Persisted configuration must be a mapping")

    preferences = payload.get("preferences", {})
    if not isinstance(preferences, dict):
        raise ValueError("Persisted configuration preferences must be a mapping")

    completed = preferences.get("onboarding_completed", False)
    if not isinstance(completed, bool):
        raise ValueError("Persisted onboarding completion state must be a boolean")
    return completed


def build_onboarding_template() -> SystemConfigModel:
    template = SystemConfigModel()
    template.llm.providers = {}
    for selection in template.llm.selections.values():
        selection.provider_id = ""
        selection.model = ""
        selection.embedding_dimension = None
        selection.provider_options = {}

    template.preferences.onboarding_completed = False
    template.preferences.user_mode = None
    return template


def resolve_personality_language_code(language: str) -> str:
    return language_family(language, default="zh")


def quick_mode_personality_locale_candidates(language: str) -> List[str]:
    preferred = resolve_personality_language_code(language)
    candidates = [preferred]
    for fallback in ("en", "zh"):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def quick_mode_personality_sort_key(preset_file: Path, payload: Dict[str, Any]) -> tuple[int, int, str, str]:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    is_default = bool(
        meta.get("default")
        or meta.get("recommended")
        or meta.get("is_default")
        or meta.get("is_recommended")
    )
    try:
        order = int(meta.get("order", 0))
    except (TypeError, ValueError):
        order = 0
    name = str(payload.get("name") or preset_file.stem)
    return (0 if is_default else 1, order, name, preset_file.stem)


def quick_mode_personality_seed_slug(locale: str, scenario: Optional[str]) -> Optional[str]:
    scenario_key = scenario if scenario in QUICK_MODE_PERSONALITY_SEEDS else "default"
    return QUICK_MODE_PERSONALITY_SEEDS.get(scenario_key, {}).get(locale)


def load_quick_mode_personality(
    language: str,
    scenario: Optional[str] = None,
) -> Optional[FullPersonalityConfigModel]:
    """Load the locale-appropriate quick-mode personality seed for a scenario."""
    root = get_backend_root() / "personalities"
    for lang in quick_mode_personality_locale_candidates(language):
        seed_dir = root / lang
        if not seed_dir.is_dir():
            continue

        preferred_seed_slug = quick_mode_personality_seed_slug(lang, scenario)
        if preferred_seed_slug:
            preset_file = seed_dir / f"{preferred_seed_slug}.json"
            if preset_file.is_file():
                try:
                    payload = json.loads(preset_file.read_text(encoding="utf-8"))
                    logger.info(
                        "Using quick-mode personality preset %s for language %s and scenario %s",
                        preferred_seed_slug,
                        lang,
                        scenario or "default",
                    )
                    return FullPersonalityConfigModel.model_validate(payload)
                except Exception as exc:
                    logger.warning(
                        "Failed to load quick-mode personality preset from %s: %s",
                        preset_file,
                        exc,
                    )

        candidates: list[tuple[tuple[int, int, str, str], Path, Dict[str, Any]]] = []
        for preset_file in sorted(seed_dir.glob("*.json")):
            try:
                payload = json.loads(preset_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to read quick-mode personality preset from %s: %s", preset_file, exc)
                continue
            candidates.append((quick_mode_personality_sort_key(preset_file, payload), preset_file, payload))

        for _, preset_file, payload in sorted(candidates, key=lambda item: item[0]):
            try:
                logger.info("Using quick-mode personality preset %s for language %s", preset_file.stem, lang)
                return FullPersonalityConfigModel.model_validate(payload)
            except Exception as exc:
                logger.warning("Failed to load quick-mode personality preset from %s: %s", preset_file, exc)

    return None


__all__ = [
    "build_onboarding_template",
    "load_quick_mode_personality",
    "quick_mode_personality_seed_slug",
    "quick_mode_personality_locale_candidates",
    "quick_mode_personality_sort_key",
    "read_onboarding_completed",
    "resolve_personality_language_code",
]
