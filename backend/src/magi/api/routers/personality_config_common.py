"""Shared helpers for personality config routes."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any, Dict, List, Optional

from ...config.models import LLMSettings
from ...identity.defaults import CANONICAL_LOCAL_USER
from ...personality.loader import PersonalityConfig
from .personality_config_schemas import PersonalityConfigModel, PersonalityDiff


def legacy_personality_config_module() -> ModuleType:
    return import_module("magi.api.routers.personality_config")


async def _load_current_config(slug: str) -> PersonalityConfig:
    """Return the PersonalityConfig for *slug*."""
    legacy = legacy_personality_config_module()
    cached = legacy.get_current_personality_config()
    if cached is not None:
        return cached
    resolved = await legacy.resolve_persona_config(slug)
    if resolved is not None:
        return resolved
    legacy.logger.warning("Persona '%s' not found in registry, using default config", slug)
    return legacy.PersonalityConfig()


async def _get_growth_engine():
    """Return the shared GrowthMemoryEngine singleton."""
    legacy = legacy_personality_config_module()
    return await legacy.get_shared_growth_engine()


async def _get_bootstrap_service():
    """Create a BootstrapDialogueService wired to the shared growth engine."""
    legacy = legacy_personality_config_module()
    engine = await legacy._get_growth_engine()
    return legacy.BootstrapDialogueService(
        growth_engine=engine,
        memory_snippet_provider=_fetch_bootstrap_memory_snippet,
    )


async def _fetch_bootstrap_memory_snippet() -> Optional[str]:
    """Return governed portrait context for the first opening, or None."""
    try:
        from ...context.user_profile_service import UserProfileService
        from ...memory.provider import get_unified_memory

        memory = get_unified_memory()
    except Exception as exc:  # noqa: BLE001 - best-effort, never block the opening
        legacy_personality_config_module().logger.info(
            "bootstrap memory unavailable: %s",
            exc,
        )
        return None

    try:
        lines = await UserProfileService(
            unified_memory=memory,
        ).get_portrait_prompt_summary(str(CANONICAL_LOCAL_USER))
        cleaned = [str(line).strip() for line in lines if str(line).strip()]
        return "\n".join(f"- {line}" for line in cleaned) or None
    except Exception as exc:  # noqa: BLE001 - best-effort, never block the opening
        legacy_personality_config_module().logger.info(
            "bootstrap portrait context unavailable: %s",
            exc,
        )
        return None


async def _get_runtime_status_snapshot() -> Dict[str, Any]:
    """Read the current runtime readiness snapshot."""
    from ..services import get_runtime_system_status

    return await get_runtime_system_status(None)


async def _wait_for_bootstrap_runtime_ready() -> Dict[str, Any]:
    """Wait briefly for the LLM bootstrap path to become available."""
    legacy = legacy_personality_config_module()
    runtime_status = await legacy._get_runtime_status_snapshot()
    if runtime_status.get("llm_ready"):
        return runtime_status

    waited_seconds = 0.0
    for delay_seconds in legacy.BOOTSTRAP_RUNTIME_WAIT_SCHEDULE_SECONDS:
        await legacy.asyncio.sleep(delay_seconds)
        waited_seconds += delay_seconds
        runtime_status = await legacy._get_runtime_status_snapshot()
        if runtime_status.get("llm_ready"):
            legacy.logger.info(
                "Bootstrap runtime became llm-ready after %.2fs wait (startup_state=%s, deferred_reason=%s)",
                waited_seconds,
                runtime_status.get("startup_state"),
                runtime_status.get("deferred_reason"),
            )
            return runtime_status

    legacy.logger.info(
        "Bootstrap runtime wait exhausted after %.2fs (llm_ready=%s, startup_state=%s, deferred_reason=%s)",
        waited_seconds,
        runtime_status.get("llm_ready"),
        runtime_status.get("startup_state"),
        runtime_status.get("deferred_reason"),
    )
    return runtime_status


async def _resolve_persona_id(persona_name: str) -> str:
    """Best-effort resolution of persona_id from the persona registry."""
    legacy = legacy_personality_config_module()
    try:
        repo = legacy.PersonaRepository(str(legacy.get_runtime_paths().persona_registry_db_path))
        await repo.init()
        record = await repo.get_by_slug(persona_name)
        return record.persona_id
    except Exception:
        return ""


async def _get_journal_service():
    """Create a PersonaJournalService wired to the shared growth engine."""
    legacy = legacy_personality_config_module()
    engine = await legacy._get_growth_engine()
    return legacy.PersonaJournalService(growth_engine=engine)


def sanitize_filename(name: str) -> str:
    legacy = legacy_personality_config_module()
    return legacy.sanitize_persona_slug(name)


async def save_personality_to_registry(name: str, config: PersonalityConfigModel) -> str:
    """Save personality configuration to the persona registry."""
    legacy = legacy_personality_config_module()
    return await legacy.save_personality_config_to_registry(
        name,
        config,
        repo_factory=legacy.PersonaRepository,
        runtime_paths_loader=legacy.get_runtime_paths,
    )


def _flatten_dict(value: Any, prefix: str = "") -> Dict[str, Any]:
    legacy = legacy_personality_config_module()
    return legacy.flatten_dict(value, prefix)


def _build_diffs(from_data: Dict[str, Any], to_data: Dict[str, Any]) -> List[PersonalityDiff]:
    legacy = legacy_personality_config_module()
    return legacy.build_personality_diffs(from_data, to_data, legacy.FIELD_LABELS)


def _normalize_avatar_in_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    legacy = legacy_personality_config_module()
    payload["avatar"] = legacy.resolve_avatar_public_url(str(payload.get("avatar") or ""))
    return payload


def _normalize_generated_personality_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    legacy = legacy_personality_config_module()
    return legacy.normalize_generated_personality_payload(payload)


async def ai_generate_personality(
    description: str,
    target_language: str = "English",
    current_config: Optional[PersonalityConfigModel] = None,
    llm_override: Optional[LLMSettings] = None,
) -> PersonalityConfigModel:
    """Generate personality configuration from description using LLM."""
    result = await ai_generate_personality_result(
        description,
        target_language=target_language,
        current_config=current_config,
        llm_override=llm_override,
    )
    return result.config


async def ai_generate_personality_result(
    description: str,
    target_language: str = "English",
    current_config: Optional[PersonalityConfigModel] = None,
    llm_override: Optional[LLMSettings] = None,
):
    """Generate personality configuration plus stage metadata."""
    legacy = legacy_personality_config_module()
    return await legacy.generate_personality_config_result(
        description,
        target_language=target_language,
        current_config=current_config,
        llm_override=llm_override,
        adapter_resolver=legacy.resolve_adapter_for_scenario,
        adapter_factory=legacy.create_llm_adapter,
    )


async def ai_start_personality_generation_job(
    description: str,
    target_language: str = "English",
    current_config: Optional[PersonalityConfigModel] = None,
    llm_override: Optional[LLMSettings] = None,
) -> Dict[str, Any]:
    """Start a background personality generation job."""
    legacy = legacy_personality_config_module()
    return await legacy.start_personality_generation_job(
        description,
        target_language=target_language,
        current_config=current_config,
        llm_override=llm_override,
        adapter_resolver=legacy.resolve_adapter_for_scenario,
        adapter_factory=legacy.create_llm_adapter,
    )


async def ai_get_personality_generation_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get a background personality generation job snapshot."""
    legacy = legacy_personality_config_module()
    return await legacy.get_personality_generation_job(job_id)


__all__ = [
    "_build_diffs",
    "_flatten_dict",
    "_get_bootstrap_service",
    "_fetch_bootstrap_memory_snippet",
    "_get_growth_engine",
    "_get_journal_service",
    "_get_runtime_status_snapshot",
    "_load_current_config",
    "_normalize_avatar_in_payload",
    "_normalize_generated_personality_payload",
    "_resolve_persona_id",
    "_wait_for_bootstrap_runtime_ready",
    "ai_get_personality_generation_job",
    "ai_generate_personality",
    "ai_generate_personality_result",
    "ai_start_personality_generation_job",
    "legacy_personality_config_module",
    "sanitize_filename",
    "save_personality_to_registry",
]
