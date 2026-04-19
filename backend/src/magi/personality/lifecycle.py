"""L8 Personality Layer lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from .current_state import get_current_personality
from .persona_repository import PersonaRepository
from .persona_seed import SEED_LOCALES, seed_builtin_personas
from .self_memory import SelfMemory

logger = get_logger(__name__)


class PersonalityModule(LifecycleModule):
    """Initialize self-memory personality store (L8)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_personality",
            dependencies=("runtime_memory", "runtime_configuration", "runtime_core_dependencies"),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")

        # Resolve active persona from the registry (preferred) or filesystem fallback.
        persona_id = ""
        personality_name = self._context.core.current_personality
        repo = PersonaRepository(str(runtime_paths.persona_registry_db_path))
        await repo.init()

        # Auto-seed builtin personas when registry is empty (first run or
        # post-migration installs that completed onboarding before the
        # persona registry existed).
        existing = await repo.list_all()
        if not existing:
            logger.info("Persona registry empty, auto-seeding builtin personas")
            for locale in SEED_LOCALES:
                await seed_builtin_personas(repo, locale)

        try:
            active_id = await repo.get_active_id()
            if active_id:
                record = await repo.get(active_id)
                persona_id = record.persona_id
                personality_name = record.slug
                logger.info("Resolved active persona from registry: %s (%s)", persona_id, personality_name)
        except Exception as exc:
            logger.debug("Persona registry lookup skipped: %s", exc)

        # Filesystem fallback for pre-migration installs.
        if not persona_id:
            try:
                personality_name = get_current_personality() or personality_name
            except Exception as exc:
                logger.warning("Failed to refresh current personality from personality state: %s", exc)

        self._context.core.current_personality = personality_name

        self._context.personality.self_memory = SelfMemory(
            personality_name=personality_name,
            personalities_path=str(runtime_paths.personalities_dir),
            persona_id=persona_id,
        )
        await self._context.personality.self_memory.init()

    async def shutdown(self) -> None:
        self._context.personality.self_memory = None
