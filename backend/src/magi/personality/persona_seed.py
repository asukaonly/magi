"""Seed the persona registry from bundled personality presets.

Called once during onboarding to populate the registry with builtin personas
from ``backend/personalities/{locale}/*.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.logger import get_logger
from ..utils.packaged_paths import get_backend_root
from .persona_repository import PersonaRepository

logger = get_logger(__name__)

SEED_LOCALES = ("zh", "en")


def resolve_locale(language: str) -> str:
    """Map a user-facing language code to a seed locale folder name."""
    lang = language.lower().replace("-", "_")
    if lang.startswith("zh"):
        return "zh"
    return "en"


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

        # Skip if already seeded (idempotent).
        existing = await repo.get_by_seed_slug(seed_slug)
        if existing is not None:
            logger.debug("Seed persona '%s' already exists, skipping", seed_slug)
            continue

        try:
            raw = preset_file.read_text(encoding="utf-8")
            # Validate JSON.
            json.loads(raw)
        except Exception:
            logger.warning("Invalid seed preset, skipping: %s", preset_file)
            continue

        persona_id = await repo.create(
            config_json=raw,
            locale=locale,
            slug=seed_slug,
            is_builtin=True,
            seed_slug=seed_slug,
        )
        created_ids.append(persona_id)

    logger.info(
        "Seeded %d builtin personas for locale '%s'",
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

        bp = data.get("persona_entity", {}).get("basic_profile", {})
        meta = data.get("meta", {})
        previews.append(
            {
                "seed_slug": preset_file.stem,
                "name": bp.get("name", preset_file.stem),
                "description": bp.get("description", ""),
                "avatar": bp.get("avatar", ""),
                "group": meta.get("group", "general"),
                "order": meta.get("order", 0),
            }
        )

    previews.sort(key=lambda p: (p["order"], p["name"]))
    return previews
