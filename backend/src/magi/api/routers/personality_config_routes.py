"""Persona config CRUD, generation, and comparison routes."""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException

from ...agent.runtime import TaskAgentType
from ... import i18n as core_i18n
from ...config import get_config
from ...config.models import LLMSettings
from ..services.config_secrets import (
    llm_settings_have_masked_secrets,
    normalize_masked_llm_settings_secrets,
)
from .personality_config_common import legacy_personality_config_module
from .personality_config_schemas import (
    AIGenerateRequest,
    PersonaAdjustmentRequest,
    PersonaIdentityVerifyRequest,
    PersonaIdentityVerifyResponse,
    PersonaIntentResolveRequest,
    PersonaIntentResolutionResponse,
    PersonalityCompareResponse,
    PersonalityConfigModel,
    PersonalityResponse,
)

personality_config_core_router = APIRouter()


def _normalize_llm_override(
    llm_override: Optional[LLMSettings],
) -> Optional[LLMSettings]:
    """Restore backend-owned credentials in an onboarding LLM override."""
    if llm_override is None or not llm_settings_have_masked_secrets(llm_override):
        return llm_override
    return normalize_masked_llm_settings_secrets(llm_override, get_config())

FIELD_LABEL_I18N_KEYS: Dict[str, str] = {
    "name": "personality.config.fields.name",
    "description": "personality.config.fields.description",
    "avatar": "personality.config.fields.avatar",
    "identity_core.identity_statement": "personality.config.fields.identity_core_identity_statement",
    "identity_core.values_loved": "personality.config.fields.identity_core_values_loved",
    "identity_core.values_rejected": "personality.config.fields.identity_core_values_rejected",
    "identity_core.attention_biases": "personality.config.fields.identity_core_attention_biases",
    "idiolect.sentence_style": "personality.config.fields.idiolect_sentence_style",
    "idiolect.vocab_available": "personality.config.fields.idiolect_vocab_available",
    "idiolect.vocab_avoided": "personality.config.fields.idiolect_vocab_avoided",
    "idiolect.structural_quirks": "personality.config.fields.idiolect_structural_quirks",
    "registers": "personality.config.fields.registers",
    "quiet_hours": "personality.config.fields.quiet_hours",
    "signature_triggers": "personality.config.fields.signature_triggers",
    "persona_layers": "personality.config.fields.persona_layers",
    "dynamic_state_rules": "personality.config.fields.dynamic_state_rules",
    "appearance_prompt": "personality.config.fields.appearance_prompt",
}


def _field_labels() -> Dict[str, str]:
    legacy = legacy_personality_config_module()
    return {
        field: core_i18n.t(key, fallback=legacy.FIELD_LABELS.get(field, field))
        for field, key in FIELD_LABEL_I18N_KEYS.items()
    }


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
            message=core_i18n.t(
                "personality.config.current.retrieved",
                fallback="Successfully retrieved current personality",
            ),
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
            raise HTTPException(
                status_code=400,
                detail=core_i18n.t(
                    "personality.config.current.missing_name",
                    fallback="Missing personality name",
                ),
            )

        config = None
        try:
            repo = legacy.PersonaRepository(str(legacy.get_runtime_paths().persona_registry_db_path))
            await repo.init()
            record = await repo.get_by_slug(name)
            config = record.config
        except (KeyError, Exception) as exc:
            raise HTTPException(
                status_code=404,
                detail=core_i18n.t(
                    "personality.config.current.not_found",
                    fallback="Personality '{name}' not found",
                    name=name,
                ),
            ) from exc

        if not legacy.set_current_personality_name(name, config=config):
            raise HTTPException(
                status_code=500,
                detail=core_i18n.t(
                    "personality.config.current.setting_failed",
                    fallback="Setting failed",
                ),
            )

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
            message=core_i18n.t(
                "personality.config.current.switched",
                fallback="Switched to personality: {name}",
                name=name,
            ),
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
            message=core_i18n.t(
                "personality.config.greeting.retrieved",
                fallback="Successfully retrieved greeting",
            ),
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
                    message=core_i18n.t(
                        "personality.config.detail.not_found_using_default",
                        fallback="Personality configuration not found, using default: {name}",
                        name=name,
                    ),
                    data=legacy._normalize_avatar_in_payload(default_config.model_dump()),
                )

        return PersonalityResponse(
            success=True,
            message=core_i18n.t(
                "personality.config.detail.retrieved",
                fallback="Successfully retrieved personality configuration: {name}",
                name=name,
            ),
            data=legacy._normalize_avatar_in_payload(config.model_dump()),
        )
    except FileNotFoundError:
        default_config = PersonalityConfigModel()
        return PersonalityResponse(
            success=True,
            message=core_i18n.t(
                "personality.config.detail.not_found_using_default",
                fallback="Personality configuration not found, using default: {name}",
                name=name,
            ),
            data=legacy._normalize_avatar_in_payload(default_config.model_dump()),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.post(
    "/",
    response_model=PersonalityResponse,
    summary="Create personality from config",
    description=(
        "Create a new personality whose name is taken from the request body. "
        "Use this instead of putting the literal string ``new`` in the path."
    ),
)
async def create_personality(config: PersonalityConfigModel):
    legacy = legacy_personality_config_module()
    actual_name = legacy.sanitize_filename(config.name)
    try:
        await legacy.save_personality_to_registry(actual_name, config)

        current = legacy.get_current_personality_name()
        if actual_name == current:
            legacy.set_current_personality_name(
                actual_name,
                config=legacy.PersonalityConfig.from_dict(config.model_dump()),
            )

        return PersonalityResponse(
            success=True,
            message=core_i18n.t(
                "personality.config.detail.saved",
                fallback="Personality configuration saved: {name}",
                name=actual_name,
            ),
            data={
                "actual_name": actual_name,
                "config": legacy._normalize_avatar_in_payload(config.model_dump()),
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.put(
    "/{name}",
    response_model=PersonalityResponse,
    summary="Save personality config",
    description="Update an existing personality, optionally renaming it to ``config.name``.",
)
async def update_personality(name: str, config: PersonalityConfigModel):
    legacy = legacy_personality_config_module()
    target_name = legacy.sanitize_filename(config.name)
    actual_name = target_name if name != target_name else name
    try:
        await legacy.save_personality_to_registry(actual_name, config)

        current = legacy.get_current_personality_name()
        if actual_name == current or name == current:
            legacy.set_current_personality_name(
                actual_name,
                config=legacy.PersonalityConfig.from_dict(config.model_dump()),
            )

        return PersonalityResponse(
            success=True,
            message=core_i18n.t(
                "personality.config.detail.saved",
                fallback="Personality configuration saved: {name}",
                name=actual_name,
            ),
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
        result = await legacy.ai_generate_personality_result(
            request.description,
            request.target_language,
            current_config=request.current_config,
            llm_override=_normalize_llm_override(request.llm_override),
            intent=request.intent,
        )
        config = result.config
        legacy.logger.info("AI generation successful: name=%s", config.name)
        return PersonalityResponse(
            success=True,
            message=core_i18n.t(
                "personality.config.generation.generated",
                fallback="AI personality configuration generated successfully",
            ),
            data=legacy._normalize_avatar_in_payload(config.model_dump()),
            stages=result.stages,
            reference_dossier=(
                result.reference_dossier.model_dump()
                if result.reference_dossier is not None
                else None
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        legacy.logger.error("AI generate personality failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.post(
    "/generation-jobs",
    response_model=PersonalityResponse,
    summary="Start AI personality generation",
    description="Start a background personality generation job and poll its status for stage progress.",
)
async def start_personality_generation(request: AIGenerateRequest):
    legacy = legacy_personality_config_module()
    try:
        snapshot = await legacy.ai_start_personality_generation_job(
            request.description,
            request.target_language,
            current_config=request.current_config,
            llm_override=_normalize_llm_override(request.llm_override),
            draft_id=request.draft_id,
            request_id=request.request_id,
            intent=request.intent,
        )
        return PersonalityResponse(
            success=True,
            message=core_i18n.t(
                "personality.config.generation.started",
                fallback="AI personality generation started",
            ),
            data=snapshot,
            stages=snapshot.get("stages"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        legacy.logger.error("AI personality generation job start failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.post(
    "/generation-intents/resolve",
    response_model=PersonaIntentResolutionResponse,
    summary="Resolve persona generation intent",
    description=(
        "Classify whether a free-text persona description references an existing "
        "prototype and return editable candidates before full generation."
    ),
)
async def resolve_personality_generation_intent(
    request: PersonaIntentResolveRequest,
) -> PersonaIntentResolutionResponse:
    legacy = legacy_personality_config_module()
    try:
        resolution = await legacy.ai_resolve_persona_generation_intent(
            request.description,
            request.target_language,
            llm_override=_normalize_llm_override(request.llm_override),
        )
        return PersonaIntentResolutionResponse(
            success=True,
            message="Persona generation intent resolved",
            data=resolution,
        )
    except HTTPException:
        raise
    except Exception as exc:
        legacy.logger.error("Persona generation intent resolution failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.post(
    "/generation-intents/verify",
    response_model=PersonaIdentityVerifyResponse,
    summary="Verify persona reference identity",
    description="Verify a selected public or fictional reference using public sources before generation.",
)
async def verify_personality_reference_identity(
    request: PersonaIdentityVerifyRequest,
) -> PersonaIdentityVerifyResponse:
    legacy = legacy_personality_config_module()
    try:
        verification = await legacy.ai_verify_persona_reference_identity(
            request.reference,
            target_language=request.target_language,
            reference_urls=request.reference_urls,
            llm_override=_normalize_llm_override(request.llm_override),
        )
        return PersonaIdentityVerifyResponse(
            success=True,
            message="Persona reference identity verified",
            data=verification,
        )
    except HTTPException:
        raise
    except Exception as exc:
        legacy.logger.error("Persona reference identity verification failed: %s", exc)
        error_code = getattr(exc, "code", None)
        if error_code:
            raise HTTPException(
                status_code=409,
                detail={"message": str(exc), "error_code": error_code},
            ) from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.post(
    "/adjust",
    response_model=PersonalityResponse,
    summary="Adjust a personality draft",
    description="Apply one scoped user adjustment to an unsaved personality configuration.",
)
async def adjust_personality(request: PersonaAdjustmentRequest) -> PersonalityResponse:
    legacy = legacy_personality_config_module()
    try:
        config = await legacy.ai_adjust_personality(
            request.current_config,
            request.instruction,
            scope=request.scope,
            target_language=request.target_language,
            intent=request.intent,
            llm_override=_normalize_llm_override(request.llm_override),
        )
        return PersonalityResponse(
            success=True,
            message="Personality draft adjusted",
            data=config.model_dump(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        legacy.logger.error("Persona adjustment failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_core_router.get(
    "/generation-jobs/{job_id}",
    response_model=PersonalityResponse,
    summary="Get AI personality generation status",
    description="Return current status and stage progress for a background personality generation job.",
)
async def get_personality_generation_status(job_id: str):
    legacy = legacy_personality_config_module()
    try:
        snapshot = await legacy.ai_get_personality_generation_job(job_id)
        if snapshot is None:
            raise HTTPException(
                status_code=404,
                detail=core_i18n.t(
                    "personality.config.generation.job_not_found",
                    fallback="Personality generation job not found",
                ),
            )
        return PersonalityResponse(
            success=True,
            message=core_i18n.t(
                "personality.config.generation.status_retrieved",
                fallback="AI personality generation status retrieved",
            ),
            data=snapshot,
            stages=snapshot.get("stages"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        legacy.logger.error("AI personality generation job status failed: %s", exc)
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
        personalities: List[str] = [s.slug for s in summaries]

        return PersonalityResponse(
            success=True,
            message=core_i18n.t(
                "personality.config.list.found",
                fallback="Found {count} personality configurations",
                count=len(personalities),
            ),
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
        repo = legacy.PersonaRepository(str(legacy.get_runtime_paths().persona_registry_db_path))
        await repo.init()
        try:
            record = await repo.get_by_slug(name)
            await repo.delete(record.persona_id)
        except (KeyError, Exception) as exc:
            raise HTTPException(
                status_code=404,
                detail=core_i18n.t(
                    "personality.config.delete.not_found",
                    fallback="Personality configuration not found",
                ),
            ) from exc

        return PersonalityResponse(
            success=True,
            message=core_i18n.t(
                "personality.config.delete.deleted",
                fallback="Personality configuration deleted: {name}",
                name=name,
            ),
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
            raise HTTPException(
                status_code=404,
                detail=core_i18n.t(
                    "personality.config.compare.not_found",
                    fallback="Personality not found: {name}",
                    name=from_name,
                ),
            )
        if to_config is None:
            raise HTTPException(
                status_code=404,
                detail=core_i18n.t(
                    "personality.config.compare.not_found",
                    fallback="Personality not found: {name}",
                    name=to_name,
                ),
            )
        from_model = PersonalityConfigModel.model_validate(from_config.to_dict())
        to_model = PersonalityConfigModel.model_validate(to_config.to_dict())
        diffs = legacy.build_personality_diffs(from_model.model_dump(), to_model.model_dump(), _field_labels())

        return PersonalityCompareResponse(
            success=True,
            message=core_i18n.t(
                "personality.config.compare.complete",
                fallback="Comparison complete: {count} differences found",
                count=len(diffs),
            ),
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
    "create_personality",
    "delete_personality",
    "generate_personality",
    "get_personality",
    "list_personalities",
    "personality_config_core_router",
    "update_personality",
    "verify_personality_reference_identity",
]
