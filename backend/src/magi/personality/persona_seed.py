"""Seed the persona registry from bundled personality presets.

Called once during onboarding to populate the registry with builtin personas
from ``backend/personalities/{locale}/*.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.logger import get_logger
from ..i18n import is_zh_language
from ..utils.packaged_paths import get_backend_root
from .persona_repository import PersonaRepository

logger = get_logger(__name__)

SEED_LOCALES = ("zh", "en")


def resolve_locale(language: str) -> str:
    """Map a user-facing language code to a seed locale folder name."""
    return "zh" if is_zh_language(language, default="en") else "en"


def _seed_dir(locale: str) -> Path:
    return get_backend_root() / "personalities" / locale


async def seed_builtin_personas(
    repo: PersonaRepository,
    locale: str,
) -> list[str]:
    """Insert all builtin personas for *locale* if none exist yet.

    Returns list of newly created persona_ids.
    """
    seed_root = _seed_dir(locale)
    if not seed_root.is_dir():
        logger.warning("Seed directory not found: %s", seed_root)
        return []

    created_ids: list[str] = []
    for preset_file in sorted(seed_root.glob("*.json")):
        seed_slug = preset_file.stem

        try:
            raw = preset_file.read_text(encoding="utf-8")
            # Validate JSON.
            json.loads(raw)
        except Exception:
            logger.warning("Invalid seed preset, skipping: %s", preset_file)
            continue

        persona_id, created = await repo.upsert_builtin(
            config_json=raw,
            locale=locale,
            seed_slug=seed_slug,
        )
        if created:
            created_ids.append(persona_id)

    logger.info(
        "Seeded %d new builtin personas for locale '%s'",
        len(created_ids),
        locale,
    )
    return created_ids


async def list_seed_previews(locale: str) -> list[dict]:
    """Return lightweight previews of available seed personas for a locale.

    Used by the onboarding UI to show persona options before they are
    inserted into the registry.
    """
    seed_root = _seed_dir(locale)
    if not seed_root.is_dir():
        return []

    previews: list[dict] = []
    for preset_file in sorted(seed_root.glob("*.json")):
        try:
            data = json.loads(preset_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        meta = data.get("meta", {})
        previews.append(
            {
                "seed_slug": preset_file.stem,
                "name": data.get("name", preset_file.stem),
                "description": data.get("description", ""),
                "avatar": data.get("avatar", ""),
                "group": meta.get("group", "general"),
                "order": meta.get("order", 0),
                "is_default": bool(meta.get("default") or meta.get("is_default")),
                "is_recommended": bool(meta.get("recommended") or meta.get("is_recommended")),
            }
        )

    previews.sort(key=lambda p: (p["order"], p["name"]))
    return previews
