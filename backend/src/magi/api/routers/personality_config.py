"""Personality configuration API router facade."""

from __future__ import annotations

import asyncio
from typing import Dict

from fastapi import APIRouter, HTTPException

from ...agent.runtime import TaskAgentType
from ...config import get_config
from ...config.models import LLMSettings
from ...core.logger import get_logger
from ...core.runtime_bindings import require_agent_runtime
from ...llm import create_llm_adapter
from ...llm.draft import resolve_adapter_for_scenario
from ...personality.active_persona import (
    get_current_personality as get_current_personality_name,
    get_current_personality_config,
    resolve_persona_config,
    set_current_personality as set_current_personality_name,
)
from ...personality.bootstrap_service import BootstrapDialogueService, get_shared_growth_engine
from ...personality.growth_memory import GrowthMemoryEngine
from ...personality.loader import PersonalityConfig
from ...personality.persona_journal_service import PersonaJournalService
from ...personality.persona_repository import PersonaRepository
from ...personality.reference_research.models import ReferenceIdentity
from ...personality.reference_research.service import verify_reference_identity
from ...personality.reference_research.tool_ports import (
    ToolReferenceFetchPort,
    ToolReferenceSearchPort,
)
from ...utils.runtime import get_runtime_paths
from ..avatar_paths import resolve_avatar_public_url
from ..services.personality_bootstrap_messages import (
    persist_bootstrap_assistant_message as _persist_bootstrap_assistant_message,
)
from ..services.personality_compare import build_personality_diffs, flatten_dict
from ..services.personality_generation import (
    PersonalityGenerationResult,
    get_personality_generation_job,
    generate_personality_config,
    generate_personality_config_result,
    normalize_generated_personality_payload,
    start_personality_generation_job,
)
from ..services.personality_generation_intent import resolve_persona_generation_intent
from ..services.personality_adjustment import adjust_personality_config
from ..services.personality_registry import sanitize_persona_slug, save_personality_config_to_registry
from .personality_bootstrap_routes import api_bootstrap_init, api_journal_reflect, personality_bootstrap_router
from .personality_config_common import (
    _build_diffs,
    _flatten_dict,
    _get_bootstrap_service,
    _get_growth_engine,
    _get_journal_service,
    _get_runtime_status_snapshot,
    _load_current_config,
    _normalize_avatar_in_payload,
    _normalize_generated_personality_payload,
    _resolve_persona_id,
    _wait_for_bootstrap_runtime_ready,
    ai_get_personality_generation_job,
    ai_generate_personality,
    ai_generate_personality_result,
    ai_adjust_personality,
    ai_resolve_persona_generation_intent,
    ai_verify_persona_reference_identity,
    ai_start_personality_generation_job,
    sanitize_filename,
    save_personality_to_registry,
)
from .personality_config_routes import (
    api_get_current_personality,
    api_get_greeting,
    api_set_current_personality,
    compare_personalities,
    create_personality,
    adjust_personality,
    delete_personality,
    generate_personality,
    get_personality_generation_status,
    get_personality,
    list_personalities,
    personality_config_core_router,
    resolve_personality_generation_intent,
    verify_personality_reference_identity,
    start_personality_generation,
    update_personality,
)
from .personality_config_schemas import (
    AIGenerateRequest,
    BootstrapConfigModel,
    BootstrapInitRequest,
    IdentityCoreModel,
    IdiolectModel,
    JournalReflectRequest,
    PersonaAdjustmentRequest,
    PersonaGenerationIntentModel,
    PersonaIntentResolveRequest,
    PersonaIntentResolutionModel,
    PersonaIntentResolutionResponse,
    PersonaIdentityVerifyRequest,
    PersonaIdentityVerifyResponse,
    PersonaReferenceCandidateModel,
    PersonaReferenceModel,
    PersonaLayerModel,
    PersonalityCompareResponse,
    PersonalityConfigModel,
    PersonalityDiff,
    PersonalityResponse,
    QuietHourModel,
    RegisterModel,
    SignatureTriggerModel,
)

logger = get_logger(__name__)
personality_config_router = APIRouter()

BOOTSTRAP_RUNTIME_WAIT_SCHEDULE_SECONDS = (0.2, 0.45, 0.9, 1.5)

FIELD_LABELS: Dict[str, str] = {
    "name": "Name",
    "description": "Description",
    "avatar": "Avatar",
    "identity_core.identity_statement": "Identity Statement",
    "identity_core.values_loved": "Values Loved",
    "identity_core.values_rejected": "Values Rejected",
    "identity_core.attention_biases": "Attention Biases",
    "idiolect.sentence_style": "Sentence Style",
    "idiolect.vocab_available": "Available Vocabulary",
    "idiolect.vocab_avoided": "Avoided Vocabulary",
    "idiolect.structural_quirks": "Structural Quirks",
    "registers": "Registers",
    "quiet_hours": "Quiet Hours",
    "signature_triggers": "Signature Triggers",
    "persona_layers": "Persona Layers",
    "dynamic_state_rules": "Dynamic State Rules",
    "appearance_prompt": "Appearance Prompt",
}

personality_config_router.include_router(personality_config_core_router)
personality_config_router.include_router(personality_bootstrap_router)

__all__ = [
    "AIGenerateRequest",
    "APIRouter",
    "BOOTSTRAP_RUNTIME_WAIT_SCHEDULE_SECONDS",
    "BootstrapConfigModel",
    "BootstrapDialogueService",
    "BootstrapInitRequest",
    "FIELD_LABELS",
    "GrowthMemoryEngine",
    "HTTPException",
    "IdentityCoreModel",
    "IdiolectModel",
    "JournalReflectRequest",
    "LLMSettings",
    "PersonaAdjustmentRequest",
    "PersonaJournalService",
    "PersonaGenerationIntentModel",
    "PersonaIdentityVerifyRequest",
    "PersonaIdentityVerifyResponse",
    "PersonaIntentResolveRequest",
    "PersonaIntentResolutionModel",
    "PersonaIntentResolutionResponse",
    "PersonaLayerModel",
    "PersonaReferenceCandidateModel",
    "PersonaReferenceModel",
    "PersonaRepository",
    "ReferenceIdentity",
    "PersonalityCompareResponse",
    "PersonalityConfig",
    "PersonalityConfigModel",
    "PersonalityDiff",
    "PersonalityGenerationResult",
    "PersonalityResponse",
    "QuietHourModel",
    "RegisterModel",
    "SignatureTriggerModel",
    "TaskAgentType",
    "_build_diffs",
    "_flatten_dict",
    "_get_bootstrap_service",
    "_get_growth_engine",
    "_get_journal_service",
    "_get_runtime_status_snapshot",
    "_load_current_config",
    "_normalize_avatar_in_payload",
    "_normalize_generated_personality_payload",
    "_persist_bootstrap_assistant_message",
    "_resolve_persona_id",
    "_wait_for_bootstrap_runtime_ready",
    "adjust_personality",
    "adjust_personality_config",
    "ai_adjust_personality",
    "ai_get_personality_generation_job",
    "ai_generate_personality",
    "ai_generate_personality_result",
    "ai_resolve_persona_generation_intent",
    "ai_verify_persona_reference_identity",
    "ai_start_personality_generation_job",
    "api_bootstrap_init",
    "api_get_current_personality",
    "api_get_greeting",
    "api_journal_reflect",
    "api_set_current_personality",
    "asyncio",
    "build_personality_diffs",
    "compare_personalities",
    "create_llm_adapter",
    "delete_personality",
    "flatten_dict",
    "generate_personality",
    "generate_personality_config",
    "generate_personality_config_result",
    "get_personality_generation_status",
    "get_personality_generation_job",
    "get_config",
    "get_current_personality_config",
    "get_current_personality_name",
    "get_personality",
    "get_runtime_paths",
    "get_shared_growth_engine",
    "list_personalities",
    "logger",
    "normalize_generated_personality_payload",
    "personality_config_router",
    "require_agent_runtime",
    "resolve_adapter_for_scenario",
    "resolve_persona_generation_intent",
    "resolve_personality_generation_intent",
    "verify_personality_reference_identity",
    "verify_reference_identity",
    "resolve_avatar_public_url",
    "resolve_persona_config",
    "sanitize_filename",
    "sanitize_persona_slug",
    "save_personality_config_to_registry",
    "save_personality_to_registry",
    "set_current_personality_name",
    "start_personality_generation_job",
    "start_personality_generation",
    "ToolReferenceFetchPort",
    "ToolReferenceSearchPort",
    "create_personality",
    "update_personality",
]
