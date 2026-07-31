"""Seed the persona registry from bundled personality presets.

Called once during onboarding to populate the registry with builtin personas
from ``backend/personalities/{locale}/*.json``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.logger import get_logger
from ..i18n import is_zh_language
from ..utils.packaged_paths import get_backend_root
from .persona_repository import PersonaRepository

if TYPE_CHECKING:
    from ..core.initialization_state import InitializationStateStore

logger = get_logger(__name__)

SEED_LOCALES = ("zh", "en")
BUILTIN_PERSONA_SEED_REVISION = "1"


def resolve_locale(language: str) -> str:
    """Map a user-facing language code to a seed locale folder name."""
    return "zh" if is_zh_language(language, default="en") else "en"


def _seed_dir(locale: str) -> Path:
    return get_backend_root() / "personalities" / locale


def seed_bundle_fingerprint(locale: str) -> str:
    """Return a deterministic fingerprint for one bundled locale directory."""
    seed_root = _seed_dir(locale)
    digest = hashlib.sha256()
    digest.update(locale.encode("utf-8"))
    if not seed_root.is_dir():
        digest.update(b"\0missing")
        return digest.hexdigest()
    for preset_file in sorted(seed_root.glob("*.json")):
        digest.update(b"\0")
        digest.update(preset_file.name.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(preset_file.read_bytes())
        except OSError:
            digest.update(b"unreadable")
    return digest.hexdigest()


async def sync_builtin_personas(
    repo: PersonaRepository,
    locale: str,
    initialization_state: InitializationStateStore,
    *,
    force: bool = False,
) -> tuple[bool, list[str]]:
    """Synchronize bundled personas only when their source bundle changed."""
    fingerprint = seed_bundle_fingerprint(locale)

    async def _seed() -> list[str]:
        return await seed_builtin_personas(repo, locale)

    ran, result = await initialization_state.run_step(
        step_id=f"builtin_personas:{locale}",
        revision=BUILTIN_PERSONA_SEED_REVISION,
        fingerprint=fingerprint,
        operation=_seed,
        force=force,
    )
    return ran, result or []


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
