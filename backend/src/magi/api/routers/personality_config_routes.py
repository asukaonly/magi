"""Persona config CRUD, generation, and comparison routes."""

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, HTTPException

from ...agent.runtime import TaskAgentType
from .personality_config_common import legacy_personality_config_module
from .personality_config_schemas import (
    AIGenerateRequest,
    PersonalityCompareResponse,
    PersonalityConfigModel,
    PersonalityResponse,
)

personality_config_core_router = APIRouter()


@personality_config_core_router.get(
    "/current",
    response_model=PersonalityResponse,
    summary="Get current personality",
    description="Return the current active personality name used by the runtime.",
)
async def api_get_current_personality():
    legacy = legacy_personality_config_module()
    try:
        return PersonalityResponse(
            success=True,
            message="Successfully retrieved current personality",
            data={"current": legacy.get_current_personality_name()},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.put(
    "/current",
    response_model=PersonalityResponse,
    summary="Set current personality",
    description="Switch the current active personality and reload agent memory if available.",
)
async def api_set_current_personality(request: Dict[str, str]):
    legacy = legacy_personality_config_module()
    try:
        name = request.get("name")
        if not name:
            raise HTTPException(status_code=400, detail="Missing personality name")

        config = None
        try:
            repo = legacy.PersonaRepository(str(legacy.get_runtime_paths().persona_registry_db_path))
            await repo.init()
            record = await repo.get_by_slug(name)
            config = record.config
        except (KeyError, Exception) as exc:
            raise HTTPException(status_code=404, detail=f"Personality '{name}' not found") from exc

        if not legacy.set_current_personality_name(name, config=config):
            raise HTTPException(status_code=500, detail="Setting failed")

        try:
            runtime = legacy.require_agent_runtime()
            manager = runtime.get_task_agent_manager()
            chat_agent = await manager.ensure_agent(TaskAgentType.CHAT, "default")
            memory = getattr(chat_agent, "memory", None)
            if memory:
                await memory.reload_personality(name, personality_config=config)
        except Exception as exc:
            legacy.logger.warning("Failed to reload agent personality: %s", exc)

        return PersonalityResponse(
            success=True,
            message=f"Switched to personality: {name}",
            data={"current": name},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.get(
    "/greeting",
    response_model=PersonalityResponse,
    summary="Get personality greeting",
    description="Return the active persona display data plus whether first-contact bootstrap is still needed.",
)
async def api_get_greeting():
    legacy = legacy_personality_config_module()
    try:
        current_name = legacy.get_current_personality_name()
        config = await legacy._load_current_config(current_name)

        needs_bootstrap = False
        needs_bootstrap_init = False
        try:
            persona_id = await legacy._resolve_persona_id(current_name)
            bootstrap_svc = await legacy._get_bootstrap_service()
            needs_bootstrap_init = await bootstrap_svc.needs_bootstrap_init(current_name, persona_id=persona_id)
            needs_bootstrap = needs_bootstrap_init
        except Exception as exc:
            legacy.logger.debug("Bootstrap status check skipped: %s", exc)

        return PersonalityResponse(
            success=True,
            message="Successfully retrieved greeting",
            data={
                "name": config.name,
                "avatar": legacy.resolve_avatar_public_url(config.avatar or ""),
                "needs_bootstrap": needs_bootstrap,
                "needs_bootstrap_init": needs_bootstrap_init,
                "bootstrap_completed": not needs_bootstrap_init,
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.get(
    "/{name}",
    response_model=PersonalityResponse,
    summary="Get personality config",
    description="Load one personality configuration by slug from the persona registry.",
)
async def get_personality(name: str = "default"):
    legacy = legacy_personality_config_module()
    try:
        try:
            resolved = await legacy.resolve_persona_config(name)
            if resolved is not None:
                config = PersonalityConfigModel.model_validate(resolved.to_dict())
            else:
                config = None
        except Exception:
            config = None

            if config is None:
                default_config = PersonalityConfigModel()
                return PersonalityResponse(
                    success=True,
                    message=f"Personality configuration not found, using default: {name}",
                    data=legacy._normalize_avatar_in_payload(default_config.model_dump()),
                )

        return PersonalityResponse(
            success=True,
            message=f"Successfully retrieved personality configuration: {name}",
            data=legacy._normalize_avatar_in_payload(config.model_dump()),
        )
    except FileNotFoundError:
        default_config = PersonalityConfigModel()
        return PersonalityResponse(
            success=True,
            message=f"Personality configuration not found, using default: {name}",
            data=legacy._normalize_avatar_in_payload(default_config.model_dump()),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.put(
    "/{name}",
    response_model=PersonalityResponse,
    summary="Save personality config",
    description="Create or update a personality configuration and handle optional rename logic.",
)
async def update_personality(name: str, config: PersonalityConfigModel, use_ai_name: bool = False):
    legacy = legacy_personality_config_module()
    target_name = legacy.sanitize_filename(config.name)
    actual_name = name
    try:
        if name == "new" or use_ai_name:
            actual_name = target_name
        elif name == legacy.DEFAULT_PERSONALITY and target_name not in {legacy.DEFAULT_PERSONALITY, "AI_Assistant"}:
            actual_name = target_name
        elif name != target_name:
            actual_name = target_name

        await legacy.save_personality_to_registry(actual_name, config)

        current = legacy.get_current_personality_name()
        if actual_name == current or name == current:
            legacy.set_current_personality_name(
                actual_name,
                config=legacy.PersonalityConfig.from_dict(config.model_dump()),
            )

        return PersonalityResponse(
            success=True,
            message=f"Personality configuration saved: {actual_name}",
            data={
                "actual_name": actual_name,
                "config": legacy._normalize_avatar_in_payload(config.model_dump()),
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.post(
    "/generate",
    response_model=PersonalityResponse,
    summary="Generate personality with AI",
    description="Generate a structured personality configuration from free-text description via LLM.",
)
async def generate_personality(request: AIGenerateRequest):
    legacy = legacy_personality_config_module()
    try:
        config = await legacy.ai_generate_personality(
            request.description,
            request.target_language,
            llm_override=request.llm_override,
        )
        legacy.logger.info("AI generation successful: name=%s", config.name)
        return PersonalityResponse(
            success=True,
            message="AI personality configuration generated successfully",
            data=legacy._normalize_avatar_in_payload(config.model_dump()),
        )
    except HTTPException:
        raise
    except Exception as exc:
        legacy.logger.error("AI generate personality failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.get(
    "/",
    response_model=PersonalityResponse,
    summary="List personalities",
    description="List available personality slugs from the persona registry.",
)
async def list_personalities():
    legacy = legacy_personality_config_module()
    try:
        repo = legacy.PersonaRepository(str(legacy.get_runtime_paths().persona_registry_db_path))
        await repo.init()
        summaries = await repo.list_all()
        personalities: List[str] = [s.slug for s in summaries if s.slug != legacy.DEFAULT_PERSONALITY]

        return PersonalityResponse(
            success=True,
            message=f"Found {len(personalities)} personality configurations",
            data={"personalities": personalities},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.delete(
    "/{name}",
    response_model=PersonalityResponse,
    summary="Delete personality",
    description="Delete one personality configuration from runtime storage.",
)
async def delete_personality(name: str):
    legacy = legacy_personality_config_module()
    try:
        if name == legacy.DEFAULT_PERSONALITY:
            raise HTTPException(status_code=400, detail="Cannot delete default personality")

        repo = legacy.PersonaRepository(str(legacy.get_runtime_paths().persona_registry_db_path))
        await repo.init()
        try:
            record = await repo.get_by_slug(name)
            await repo.delete(record.persona_id)
        except (KeyError, Exception) as exc:
            raise HTTPException(status_code=404, detail="Personality configuration not found") from exc

        return PersonalityResponse(
            success=True,
            message=f"Personality configuration deleted: {name}",
            data=None,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.get(
    "/compare/{from_name}/{to_name}",
    response_model=PersonalityCompareResponse,
    summary="Compare personalities",
    description="Compare two personality configurations and return field-level differences.",
)
async def compare_personalities(from_name: str, to_name: str):
    legacy = legacy_personality_config_module()
    try:
        from_config = await legacy.resolve_persona_config(from_name)
        to_config = await legacy.resolve_persona_config(to_name)
        if from_config is None:
            raise HTTPException(status_code=404, detail=f"Personality not found: {from_name}")
        if to_config is None:
            raise HTTPException(status_code=404, detail=f"Personality not found: {to_name}")
        from_model = PersonalityConfigModel.model_validate(from_config.to_dict())
        to_model = PersonalityConfigModel.model_validate(to_config.to_dict())
        diffs = legacy._build_diffs(from_model.model_dump(), to_model.model_dump())

        return PersonalityCompareResponse(
            success=True,
            message=f"Comparison complete: {len(diffs)} differences found",
            from_personality=from_name,
            to_personality=to_name,
            diffs=diffs,
            from_config=from_model,
            to_config=to_model,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


__all__ = [
    "api_get_current_personality",
    "api_get_greeting",
    "api_set_current_personality",
    "compare_personalities",
    "delete_personality",
    "generate_personality",
    "get_personality",
    "list_personalities",
    "personality_config_core_router",
    "update_personality",
]