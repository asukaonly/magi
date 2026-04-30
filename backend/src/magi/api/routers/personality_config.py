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
from ...utils.runtime import get_runtime_paths
from ..avatar_paths import resolve_avatar_public_url
from ..services.personality_bootstrap_messages import (
    persist_bootstrap_assistant_message as _persist_bootstrap_assistant_message,
)
from ..services.personality_compare import build_personality_diffs, flatten_dict
from ..services.personality_generation import generate_personality_config, normalize_generated_personality_payload
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
    ai_generate_personality,
    sanitize_filename,
    save_personality_to_registry,
)
from .personality_config_routes import (
    api_get_current_personality,
    api_get_greeting,
    api_set_current_personality,
    compare_personalities,
    delete_personality,
    generate_personality,
    get_personality,
    list_personalities,
    personality_config_core_router,
    update_personality,
)
from .personality_config_schemas import (
    AIGenerateRequest,
    BasicProfileModel,
    BootstrapConfigModel,
    BootstrapInitRequest,
    CoreIdentityModel,
    JournalReflectRequest,
    PersonaEntityModel,
    PersonalityCompareResponse,
    PersonalityConfigModel,
    PersonalityDiff,
    PersonalityResponse,
    StateTransitionProtocolItemModel,
)

logger = get_logger(__name__)
personality_config_router = APIRouter()

BOOTSTRAP_RUNTIME_WAIT_SCHEDULE_SECONDS = (0.2, 0.45, 0.9, 1.5)
DEFAULT_PERSONALITY = "default"

FIELD_LABELS: Dict[str, str] = {
    "persona_entity.basic_profile.name": "Name",
    "persona_entity.basic_profile.age": "Age",
    "persona_entity.basic_profile.gender": "Gender",
    "persona_entity.basic_profile.description": "Description",
    "persona_entity.basic_profile.avatar": "Avatar",
    "persona_entity.basic_profile.occupation": "Occupation",
    "persona_entity.core_identity.inner_narrative": "Inner Narrative",
    "persona_entity.core_identity.language_fingerprint": "Language Fingerprint",
    "persona_entity.core_identity.attention_bias": "Attention Bias",
    "appearance_prompt": "Appearance Prompt",
    "state_transition_protocol": "State Transition Protocol",
}

personality_config_router.include_router(personality_config_core_router)
personality_config_router.include_router(personality_bootstrap_router)

__all__ = [
    "AIGenerateRequest",
    "APIRouter",
    "BOOTSTRAP_RUNTIME_WAIT_SCHEDULE_SECONDS",
    "BasicProfileModel",
    "BootstrapConfigModel",
    "BootstrapDialogueService",
    "BootstrapInitRequest",
    "CoreIdentityModel",
    "DEFAULT_PERSONALITY",
    "FIELD_LABELS",
    "GrowthMemoryEngine",
    "HTTPException",
    "JournalReflectRequest",
    "LLMSettings",
    "PersonaEntityModel",
    "PersonaJournalService",
    "PersonaRepository",
    "PersonalityCompareResponse",
    "PersonalityConfig",
    "PersonalityConfigModel",
    "PersonalityDiff",
    "PersonalityResponse",
    "StateTransitionProtocolItemModel",
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
    "ai_generate_personality",
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
    "resolve_avatar_public_url",
    "resolve_persona_config",
    "sanitize_filename",
    "sanitize_persona_slug",
    "save_personality_config_to_registry",
    "save_personality_to_registry",
    "set_current_personality_name",
    "update_personality",
]