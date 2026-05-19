"""L8 Personality Layer lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from ..i18n import get_preferred_language
from .active_persona import set_current_personality
from .persona_repository import PersonaRepository
from .persona_seed import seed_builtin_personas, resolve_locale
from .self_memory import SelfMemory

logger = get_logger(__name__)


async def _ensure_active_persona(
    repo: PersonaRepository,
    preferred_name: str,
) -> str | None:
    """Ensure registry has an active persona and return its ID."""
    active_id = await repo.get_active_id()
    if active_id:
        record = await repo.get(active_id)
        if record:
            return active_id

    summaries = await repo.list_all()
    if not summaries:
        return None

    preferred = (preferred_name or "").strip()
    if preferred:
        for summary in summaries:
            candidates = {summary.name, summary.slug}
            if summary.seed_slug:
                candidates.add(summary.seed_slug)
            if preferred in candidates:
                await repo.set_active(summary.persona_id)
                return summary.persona_id

    fallback = summaries[0]
    await repo.set_active(fallback.persona_id)
    return fallback.persona_id


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
        personality_config = None
        repo = PersonaRepository(str(runtime_paths.persona_registry_db_path))
        await repo.init()

        # Keep builtin personas aligned with bundled presets. Custom personas
        # remain registry-owned; builtin records follow their seed files.
        existing = await repo.list_all()
        locale = resolve_locale(get_preferred_language())
        if not existing:
            logger.info(
                "Persona registry empty, auto-seeding builtin personas for locale '%s'",
                locale,
            )
        await seed_builtin_personas(repo, locale)

        try:
            active_id = await _ensure_active_persona(repo, personality_name)
            if active_id:
                record = await repo.get(active_id)
                persona_id = record.persona_id
                personality_name = record.slug
                personality_config = record.config
                logger.info("Resolved active persona from registry: %s (%s)", persona_id, personality_name)
        except Exception as exc:
            logger.debug("Persona registry lookup skipped: %s", exc)

        if not personality_name:
            raise RuntimeError(
                "PersonalityModule failed to resolve an active persona. "
                "Check that bundled persona presets exist under backend/personalities/ "
                "and that seed_builtin_personas completed without errors."
            )

        self._context.core.current_personality = personality_name
        # Synchronize the in-memory active slug and config so other modules can
        # read it synchronously through the active persona cache.
        set_current_personality(personality_name, config=personality_config)

        self._context.personality.self_memory = SelfMemory(
            personality_name=personality_name,
            persona_id=persona_id,
            personality_config=personality_config,
        )
        await self._context.personality.self_memory.init()

    async def shutdown(self) -> None:
        self._context.personality.self_memory = None
