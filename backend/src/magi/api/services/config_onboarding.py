"""Onboarding configuration assembly helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...core.logger import get_logger
from ...utils.packaged_paths import get_backend_root
from ..routers.config_schemas import (
    FullPersonalityConfigModel,
    SystemConfigModel,
)

logger = get_logger(__name__)


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
    normalized = (language or "zh").lower()
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("en"):
        return "en"
    return normalized


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


def load_quick_mode_default_personality(language: str) -> Optional[FullPersonalityConfigModel]:
    """Load the locale-appropriate quick-mode personality seed."""
    root = get_backend_root() / "personalities"
    for lang in quick_mode_personality_locale_candidates(language):
        seed_dir = root / lang
        if not seed_dir.is_dir():
            continue

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
    "load_quick_mode_default_personality",
    "quick_mode_personality_locale_candidates",
    "quick_mode_personality_sort_key",
    "resolve_personality_language_code",
]