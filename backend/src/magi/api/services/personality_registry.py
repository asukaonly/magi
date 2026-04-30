"""Persona registry helpers used by the personality config API."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from ...core.logger import get_logger
from ...personality.persona_repository import PersonaRepository
from ...utils.runtime import RuntimePaths, get_runtime_paths
from ..routers.personality_config_schemas import PersonalityConfigModel

logger = get_logger(__name__)


def sanitize_persona_slug(name: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", name).replace(" ", "_")
    return (sanitized[:50] or "unnamed").strip("_") or "unnamed"


async def save_personality_config_to_registry(
    name: str,
    config: PersonalityConfigModel,
    *,
    repo_factory: Callable[[str], Any] = PersonaRepository,
    runtime_paths_loader: Callable[[], RuntimePaths] = get_runtime_paths,
) -> str:
    """Create or update a persona registry entry and return its slug."""
    config_json = json.dumps(config.model_dump(), ensure_ascii=False)
    repo = repo_factory(str(runtime_paths_loader().persona_registry_db_path))
    await repo.init()
    try:
        record = await repo.get_by_slug(name)
        await repo.update(record.persona_id, config_json=config_json, slug=name)
        return name
    except (KeyError, Exception):
        persona_id = await repo.create(config_json=config_json, slug=name)
        logger.info("Created new persona in registry: %s (%s)", name, persona_id)
        return name


__all__ = ["sanitize_persona_slug", "save_personality_config_to_registry"]