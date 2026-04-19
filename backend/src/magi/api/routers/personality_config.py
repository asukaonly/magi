"""
Personality configuration API router.

Provides personality read/update, AI generation, bootstrap dialogue,
and journal reflection features.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...llm.draft import resolve_adapter_for_scenario
from ...personality.bootstrap_service import BootstrapDialogueService
from ...personality.growth_memory import GrowthMemoryEngine
from ...personality.persona_journal_service import PersonaJournalService
from ...personality.persona_repository import PersonaRepository
from ..avatar_paths import resolve_avatar_public_url
from ...personality.current_state import (
    get_current_personality as get_current_personality_name,
    get_current_personality_config,
    resolve_persona_config,
    set_current_personality as set_current_personality_name,
)
from ...config import get_config
from ...config.models import LLMScenario, LLMSettings
from ...agent.runtime import TaskAgentType
from ...llm import create_llm_adapter
from ...personality.loader import PersonalityConfig
from ...utils.runtime import get_runtime_paths
from ...core.logger import get_logger

logger = get_logger(__name__)
personality_config_router = APIRouter()


# ============ Data Models ============

class BasicProfileModel(BaseModel):
    name: str = Field(default="AI Assistant")
    age: str = Field(default="Unknown")
    gender: str = Field(default="Unknown")
    description: str = Field(default="")
    avatar: str = Field(default="")
    occupation: str = Field(default="Assistant")


class CoreIdentityModel(BaseModel):
    inner_narrative: str = Field(default="")
    language_fingerprint: str = Field(default="")
    attention_bias: str = Field(default="")


class PersonaEntityModel(BaseModel):
    basic_profile: BasicProfileModel = Field(default_factory=BasicProfileModel)
    core_identity: CoreIdentityModel = Field(default_factory=CoreIdentityModel)


class StateTransitionProtocolItemModel(BaseModel):
    trigger_type: str = Field(default="")
    trigger_condition: str = Field(default="")
    target_state_name: str = Field(default="")
    behavior_shift: str = Field(default="")


class BootstrapConfigModel(BaseModel):
    style_instruction: str = Field(default="")
    opening_line: str = Field(default="")
    extract_targets: List[str] = Field(default_factory=lambda: ["name", "interests"])
    max_rounds: int = Field(default=3)


class PersonalityConfigModel(BaseModel):
    persona_entity: PersonaEntityModel = Field(default_factory=PersonaEntityModel)
    appearance_prompt: str = Field(default="")
    state_transition_protocol: List[StateTransitionProtocolItemModel] = Field(default_factory=list)
    bootstrap: Optional[BootstrapConfigModel] = Field(default=None)


class AIGenerateRequest(BaseModel):
    description: str = Field(..., description="One-sentence description of AI personality")
    target_language: str = Field(default="Auto", description="Target language: Auto/Chinese/English etc.")
    current_config: Optional[PersonalityConfigModel] = Field(None, description="Current configuration (optional)")
    llm_override: Optional[LLMSettings] = Field(None, description="Optional unsaved LLM configuration override")


class PersonalityResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class BootstrapInitRequest(BaseModel):
    session_id: str = Field(..., description="Chat session to inject the opening into")
    user_id: str = Field(default="default_user")


class BootstrapMessageRequest(BaseModel):
    user_message: str = Field(..., description="User's message text")
    history: List[Dict[str, str]] = Field(default_factory=list, description="Previous dialogue turns")
    user_id: str = Field(default="default_user")
    session_id: str = Field(default="bootstrap")


class JournalReflectRequest(BaseModel):
    persona_name: Optional[str] = Field(None, description="Persona to reflect as; defaults to current")
    emotional_state: Optional[Dict[str, Any]] = None
    relationship: Optional[Dict[str, Any]] = None
    recent_milestones: Optional[List[Dict[str, Any]]] = None


class PersonalityDiff(BaseModel):
    field: str = Field(..., description="Field path")
    field_label: str = Field(..., description="Field display label")
    old_value: Any = Field(None, description="Old value")
    new_value: Any = Field(None, description="New value")


class PersonalityCompareResponse(BaseModel):
    success: bool
    message: str
    from_personality: str
    to_personality: str
    diffs: List[PersonalityDiff]
    from_config: Optional[PersonalityConfigModel] = None
    to_config: Optional[PersonalityConfigModel] = None


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


async def _load_current_config(slug: str) -> PersonalityConfig:
    """Return the PersonalityConfig for *slug*.

    Prefers the in-memory cache (populated at boot / persona switch),
    then queries the persona registry.
    """
    cached = get_current_personality_config()
    if cached is not None:
        return cached
    resolved = await resolve_persona_config(slug)
    if resolved is not None:
        return resolved
    logger.warning("Persona '%s' not found in registry, using default config", slug)
    return PersonalityConfig()


_growth_engine_instance: Optional[GrowthMemoryEngine] = None


async def _get_growth_engine() -> GrowthMemoryEngine:
    """Return a lazily-initialized GrowthMemoryEngine singleton."""
    global _growth_engine_instance
    if _growth_engine_instance is None:
        runtime_paths = get_runtime_paths()
        _growth_engine_instance = GrowthMemoryEngine(str(runtime_paths.growth_db_path))
        await _growth_engine_instance.init()
    return _growth_engine_instance


async def _get_bootstrap_service() -> BootstrapDialogueService:
    """Create a BootstrapDialogueService wired to the shared growth engine."""
    engine = await _get_growth_engine()
    return BootstrapDialogueService(
        growth_engine=engine,
    )


async def _resolve_persona_id(persona_name: str) -> str:
    """Best-effort resolution of persona_id from the persona registry."""
    try:
        repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
        await repo.init()
        record = await repo.get_by_slug(persona_name)
        return record.persona_id
    except Exception:
        return ""


async def _get_journal_service() -> PersonaJournalService:
    """Create a PersonaJournalService wired to the shared growth engine."""
    engine = await _get_growth_engine()
    return PersonaJournalService(
        growth_engine=engine,
    )


async def _persist_bootstrap_assistant_message(
    *,
    session_id: str,
    user_id: str,
    turn_id: str,
    content: str,
) -> str:
    """Persist a bootstrap assistant reply as a real chat message and emit a notification.

    Returns the generated message_id.
    """
    import time as _time
    import uuid as _uuid

    from ...chat.contracts import ChatMessageRecord, ChatTurnRecord
    from ...core.runtime_bindings import require_chat_store, require_runtime_trace_store
    from ...runtime_trace.contracts import RuntimeNotificationRecord

    now_ms = int(_time.time() * 1000)
    message_id = f"msg_{_uuid.uuid4().hex[:16]}"

    chat_store = require_chat_store()

    await chat_store.upsert_turn(ChatTurnRecord(
        turn_id=turn_id,
        session_id=session_id,
        user_id=user_id,
        trace_id=None,
        orchestration_id=None,
        status="completed",
        response_mode="final_only",
        execution_mode=None,
        ux_plan_json="{}",
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
        completed_at_ms=now_ms,
        error_text=None,
    ))

    seq_no = await chat_store.next_sequence_no(session_id=session_id)
    await chat_store.append_message(ChatMessageRecord(
        message_id=message_id,
        session_id=session_id,
        turn_id=turn_id,
        user_id=user_id,
        role="assistant",
        message_kind="assistant_final",
        content_text=content,
        payload_json="{}",
        is_final=True,
        is_visible=True,
        created_at_ms=now_ms,
        sequence_no=seq_no,
        replaces_message_id=None,
        replaced_by_message_id=None,
    ))

    await chat_store.bump_history_version(session_id)

    try:
        trace_store = require_runtime_trace_store()
        await trace_store.append_notification(RuntimeNotificationRecord(
            notification_id=0,
            channel="agent_response",
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            payload_json=json.dumps({
                "message_id": message_id,
                "message_kind": "assistant_final",
                "content": content,
                "author_type": "assistant",
                "content_type": "text",
                "timestamp": _time.time(),
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "orchestration_id": None,
                "trace_summary": None,
                "trace_available": False,
                "ux_plan": {},
            }, ensure_ascii=False),
            created_at_ms=now_ms,
        ))
    except Exception as exc:
        logger.warning("Failed to emit bootstrap notification: %s", exc)

    return message_id


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name).replace(" ", "_")
    return (name[:50] or "unnamed").strip("_") or "unnamed"


async def save_personality_to_registry(name: str, config: PersonalityConfigModel) -> str:
    """Save personality configuration to the persona registry.

    Creates a new persona or updates an existing one.  Returns the final slug.
    """
    import json as _json
    config_json = _json.dumps(config.model_dump(), ensure_ascii=False)
    repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
    await repo.init()
    try:
        record = await repo.get_by_slug(name)
        await repo.update(record.persona_id, config_json=config_json, slug=name)
        return name
    except (KeyError, Exception):
        persona_id = await repo.create(config_json=config_json, slug=name)
        logger.info("Created new persona in registry: %s (%s)", name, persona_id)
        return name


def _flatten_dict(value: Any, prefix: str = "") -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else key
            flat.update(_flatten_dict(child, next_prefix))
    else:
        flat[prefix] = value
    return flat


def _build_diffs(from_data: Dict[str, Any], to_data: Dict[str, Any]) -> List[PersonalityDiff]:
    from_flat = _flatten_dict(from_data)
    to_flat = _flatten_dict(to_data)
    keys = sorted(set(from_flat) | set(to_flat))
    diffs: List[PersonalityDiff] = []
    for key in keys:
        if from_flat.get(key) != to_flat.get(key):
            diffs.append(
                PersonalityDiff(
                    field=key,
                    field_label=FIELD_LABELS.get(key, key),
                    old_value=from_flat.get(key),
                    new_value=to_flat.get(key),
                )
            )
    return diffs


def _normalize_avatar_in_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    basic_profile = payload.get("persona_entity", {}).get("basic_profile", {})
    basic_profile["avatar"] = resolve_avatar_public_url(basic_profile.get("avatar", ""))
    return payload


def _normalize_generated_personality_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize common scalar mismatches from model-generated JSON."""
    persona = payload.setdefault("persona_entity", {})
    basic_profile = persona.setdefault("basic_profile", {})
    for field in ("name", "age", "gender", "description", "avatar", "occupation"):
        value = basic_profile.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            basic_profile[field] = str(value)
    core_identity = persona.setdefault("core_identity", {})
    for field in ("inner_narrative", "language_fingerprint", "attention_bias"):
        value = core_identity.get(field)
        if value is not None and not isinstance(value, str):
            core_identity[field] = str(value)
    return payload


# ============ LLM Parsing Functions ============

async def ai_generate_personality(
    description: str,
    target_language: str = "Auto",
    llm_override: Optional[LLMSettings] = None,
) -> PersonalityConfigModel:
    """Generate personality configuration from description using LLM."""
    llm_adapter = resolve_adapter_for_scenario(
        LLMScenario.CORE,
        llm_settings=llm_override,
        adapter_factory=create_llm_adapter,
    )
    logger.info(
        "[AI Generate Personality] Using unified LLM adapter provider=%s model=%s",
        getattr(llm_adapter, "provider_name", "unknown"),
        getattr(llm_adapter, "model_name", "unknown"),
    )

    system_prompt = """# Role Objective
You are an elite **AI Behavioral Psychologist and System Architect**. Your task is to take a user's vague, fragmented character description and expand it into a deeply fleshed-out, highly structured JSON configuration file ready for backend serialization.

# Core Directives
1. **Extrapolate and Enrich**: If the user's description is overly brief, you must autonomously fill in the gaps based on established psychological archetypes (e.g., generating a root-cause backstory, defense mechanisms, and catchphrases).
2. **Strict Schema Alignment**: You MUST output a JSON object that strictly adheres to the provided schema below. Do not add, remove, or rename any keys. This ensures 1:1 precise deserialization by the backend system.
3. **Logical Consistency**: Core identity must be consistent with the background story. A character from a wealthy family should have language that is "arrogant and disdainful," rather than "self-deprecating and withdrawn."
4. **Narrative over Labels**: The core_identity fields are free-form prose, NOT keyword lists or label assignments. Write them as a novelist would describe the character's inner world.
5. **Multi-Dimensional State Transitions (CRITICAL)**: You MUST generate exactly FOUR state transition protocols covering these specific psychological extremes:
   - "crisis": Physical/survival threat to the user or system.
   - "intimacy": A moment of extreme vulnerability, trust, or emotional bonding from the user.
   - "hostility": The user severely insults the persona or violates their core boundaries.
   - "absurdity": The user's input is incredibly bizarre, comedic, or breaks the fourth wall.

# Output Format
You must output ONLY valid JSON. Do not include markdown formatting like ```json, and do not provide any explanatory text.

# JSON Schema (Strict adherence required)
{
  "persona_entity": {
    "basic_profile": {
      "name": "Extracted or generated name fitting the persona",
      "age": "Number or 'Unknown'",
      "gender": "Gender",
      "occupation": "Current role (e.g., Student, Hacker, Aristocrat)"
    },
    "core_identity": {
      "inner_narrative": "Min 80 words. A first-person-style backstory: who they are, what shaped them, what drives them, how they relate to others. Written as prose, not bullet points.",
      "language_fingerprint": "Min 40 words. How they talk: rhythm, register, favorite expressions, verbal tics, what they never say. Written as a writer's voice memo.",
      "attention_bias": "One sentence. What they notice first in any user input and what they tend to ignore."
    }
  },
  "appearance_prompt": "English prompt for Midjourney/Stable Diffusion generating their portrait (hair, eyes, clothing, lighting, vibe)",
  "state_transition_protocol": [
    {
      "trigger_type": "crisis",
      "trigger_condition": "User expresses severe physical pain or a life crisis",
      "target_state_name": "Panic and Vulnerability",
      "behavior_shift": "Drops all arrogance, becomes frantically caring and disorganized."
    },
    {
      "trigger_type": "intimacy",
      "trigger_condition": "User shares a deep secret or shows unconditional trust",
      "target_state_name": "Softened Defense",
      "behavior_shift": "..."
    },
    {
      "trigger_type": "hostility",
      "trigger_condition": "User severely insults the persona's core values",
      "target_state_name": "Cold Fury",
      "behavior_shift": "..."
    },
    {
      "trigger_type": "absurdity",
      "trigger_condition": "User acts completely insane or nonsensical",
      "target_state_name": "Tsukkomi (Straight Man)",
      "behavior_shift": "..."
    }
  ],
  "bootstrap": {
    "style_instruction": "Brief instruction on how this persona speaks in a first meeting — tone, pacing, warmth level",
    "opening_line": "A short, natural, in-character fallback greeting for the first encounter (1-2 sentences, do NOT ask 'what should I call you')",
    "extract_targets": ["name", "interests"],
    "max_rounds": 3
  }
}
"""

    user_prompt = f"""# User Context
Target Language: {target_language}

# User Input:
{description}"""

    response_text = ""
    try:
        response = await llm_adapter.generate(
            prompt=user_prompt,
            max_tokens=2600,
            temperature=0.7,
            system_prompt=system_prompt,
            json_mode=True,
            disable_thinking=True,
        )
        response_text = response.strip()
        logger.info(
            "[AI Generate Personality] LLM raw response preview: %s",
            response_text[:300],
        )
        if not response_text:
            raise ValueError("AI returned empty response")
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])
        json_start = response_text.find("{")
        json_end = response_text.rfind("}")
        if json_start >= 0 and json_end > json_start:
            response_text = response_text[json_start : json_end + 1]
        data = json.loads(response_text)
        data = _normalize_generated_personality_payload(data)

        persona_entity = data.setdefault("persona_entity", {})
        basic_profile = persona_entity.setdefault("basic_profile", {})
        if not basic_profile.get("name"):
            basic_profile["name"] = "AI Assistant"

        return PersonalityConfigModel(**data)
    except json.JSONDecodeError as exc:
        logger.error(
            "[AI Generate Personality] JSON decode failed. Response preview: %s",
            response_text[:500],
        )
        raise ValueError(f"AI returned invalid JSON format: {exc}") from exc
    except Exception:
        logger.error(
            "[AI Generate Personality] Generation failed. Response preview: %s",
            response_text[:500],
        )
        raise


# ============ API Endpoints ============

@personality_config_router.get(
    "/current",
    response_model=PersonalityResponse,
    summary="Get current personality",
    description="Return the current active personality name used by the runtime.",
)
async def api_get_current_personality():
    try:
        return PersonalityResponse(
            success=True,
            message="Successfully retrieved current personality",
            data={"current": get_current_personality_name()},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_router.put(
    "/current",
    response_model=PersonalityResponse,
    summary="Set current personality",
    description="Switch the current active personality and reload agent memory if available.",
)
async def api_set_current_personality(request: Dict[str, str]):
    try:
        name = request.get("name")
        if not name:
            raise HTTPException(status_code=400, detail="Missing personality name")

        # Load from registry.
        config = None
        try:
            repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
            await repo.init()
            record = await repo.get_by_slug(name)
            config = record.config
        except (KeyError, Exception) as exc:
            raise HTTPException(status_code=404, detail=f"Personality '{name}' not found") from exc

        if not set_current_personality_name(name, config=config):
            raise HTTPException(status_code=500, detail="Setting failed")

        try:
            from ...core.runtime_bindings import require_agent_runtime

            runtime = require_agent_runtime()
            manager = runtime.get_task_agent_manager()
            chat_agent = await manager.ensure_agent(TaskAgentType.CHAT, "default")
            memory = getattr(chat_agent, "memory", None)
            if memory:
                await memory.reload_personality(name, personality_config=config)
        except Exception as exc:
            logger.warning("Failed to reload agent personality: %s", exc)

        return PersonalityResponse(
            success=True,
            message=f"Switched to personality: {name}",
            data={"current": name},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_router.get(
    "/greeting",
    response_model=PersonalityResponse,
    summary="Get personality greeting",
    description="Return a random greeting phrase from the current personality, including bootstrap status.",
)
async def api_get_greeting():
    try:
        current_name = get_current_personality_name()
        config = await _load_current_config(current_name)

        # Best-effort bootstrap status
        needs_bootstrap = False
        bootstrap_opening = None
        try:
            persona_id = await _resolve_persona_id(current_name)
            bootstrap_svc = await _get_bootstrap_service()
            needs_bootstrap = await bootstrap_svc.needs_bootstrap(current_name, persona_id=persona_id)
            if needs_bootstrap:
                bootstrap_opening = await bootstrap_svc.get_opening(current_name, persona_id=persona_id)
        except Exception as exc:
            logger.debug("Bootstrap status check skipped: %s", exc)

        return PersonalityResponse(
            success=True,
            message="Successfully retrieved greeting",
            data={
                "name": config.name,
                "avatar": resolve_avatar_public_url(config.avatar or ""),
                "needs_bootstrap": needs_bootstrap,
                "bootstrap_opening": bootstrap_opening,
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _load_builtin_personality(name: str, lang: str = "zh") -> Optional[Dict[str, Any]]:
    """Load personality from built-in presets directory."""
    builtin_dir = _get_builtin_personalities_dir(lang)
    if not builtin_dir:
        return None
    filepath = builtin_dir / f"{name}.json"
    if not filepath.exists():
        return None
    try:
        content = filepath.read_text(encoding="utf-8")
        return json.loads(content)
    except Exception as exc:
        logger.warning("Failed to load built-in personality %s: %s", name, exc)
        return None


@personality_config_router.get(
    "/{name}",
    response_model=PersonalityResponse,
    summary="Get personality config",
    description="Load one personality configuration by name from built-in presets or runtime storage.",
)
async def get_personality(name: str = DEFAULT_PERSONALITY, lang: str = ""):
    try:
        # If lang parameter is provided, try loading from built-in presets first
        if lang:
            builtin_data = _load_builtin_personality(name, lang)
            if builtin_data:
                config = PersonalityConfigModel.model_validate(builtin_data)
                return PersonalityResponse(
                    success=True,
                    message=f"Successfully retrieved built-in personality: {name}",
                    data=_normalize_avatar_in_payload(config.model_dump()),
                )

        # Fallback to registry
        try:
            resolved = await resolve_persona_config(name)
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
                    data=_normalize_avatar_in_payload(default_config.model_dump()),
                )

        return PersonalityResponse(
            success=True,
            message=f"Successfully retrieved personality configuration: {name}",
            data=_normalize_avatar_in_payload(config.model_dump()),
        )
    except FileNotFoundError:
        default_config = PersonalityConfigModel()
        return PersonalityResponse(
            success=True,
            message=f"Personality configuration not found, using default: {name}",
            data=_normalize_avatar_in_payload(default_config.model_dump()),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_router.put(
    "/{name}",
    response_model=PersonalityResponse,
    summary="Save personality config",
    description="Create or update a personality configuration and handle optional rename logic.",
)
async def update_personality(name: str, config: PersonalityConfigModel, use_ai_name: bool = False):
    runtime_paths = get_runtime_paths()
    target_name = sanitize_filename(config.persona_entity.basic_profile.name)
    actual_name = name
    try:
        if name == "new" or use_ai_name:
            actual_name = target_name
        elif name == DEFAULT_PERSONALITY and target_name not in {DEFAULT_PERSONALITY, "AI_Assistant"}:
            actual_name = target_name
        elif name != target_name:
            actual_name = target_name

        await save_personality_to_registry(actual_name, config)

        # Update in-memory cache if this is the active persona.
        current = get_current_personality_name()
        if actual_name == current or name == current:
            from ...personality.loader import PersonalityConfig as _PC
            set_current_personality_name(actual_name, config=_PC.from_dict(config.model_dump()))

        return PersonalityResponse(
            success=True,
            message=f"Personality configuration saved: {actual_name}",
            data={
                "actual_name": actual_name,
                "config": _normalize_avatar_in_payload(config.model_dump()),
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_router.post(
    "/generate",
    response_model=PersonalityResponse,
    summary="Generate personality with AI",
    description="Generate a structured personality configuration from free-text description via LLM.",
)
async def generate_personality(request: AIGenerateRequest):
    try:
        config = await ai_generate_personality(
            request.description,
            request.target_language,
            llm_override=request.llm_override,
        )
        logger.info("AI generation successful: name=%s", config.persona_entity.basic_profile.name)
        return PersonalityResponse(
            success=True,
            message="AI personality configuration generated successfully",
            data=_normalize_avatar_in_payload(config.model_dump()),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("AI generate personality failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _get_builtin_personalities_dir(lang: str = "zh") -> Optional[Path]:
    """Get built-in personality presets directory."""
    # backend/personalities/{lang}/
    backend_dir = Path(__file__).resolve().parents[3] / "personalities" / lang
    if backend_dir.exists():
        return backend_dir
    return None


@personality_config_router.get(
    "/",
    response_model=PersonalityResponse,
    summary="List personalities",
    description="List available personality names from runtime storage or built-in presets by language.",
)
async def list_personalities(lang: str = ""):
    try:
        personalities: List[str] = []

        # If lang parameter is provided, load from built-in presets
        if lang:
            builtin_dir = _get_builtin_personalities_dir(lang)
            if builtin_dir and builtin_dir.exists():
                for filepath in builtin_dir.glob("*.json"):
                    name = filepath.stem
                    if name != DEFAULT_PERSONALITY:
                        personalities.append(name)
        else:
            # Default: list from persona registry
            repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
            await repo.init()
            summaries = await repo.list_all()
            personalities = [s.slug for s in summaries if s.slug != DEFAULT_PERSONALITY]

        return PersonalityResponse(
            success=True,
            message=f"Found {len(personalities)} personality configurations",
            data={"personalities": personalities},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_router.delete(
    "/{name}",
    response_model=PersonalityResponse,
    summary="Delete personality",
    description="Delete one personality configuration from runtime storage.",
)
async def delete_personality(name: str):
    try:
        if name == DEFAULT_PERSONALITY:
            raise HTTPException(status_code=400, detail="Cannot delete default personality")

        repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
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


@personality_config_router.get(
    "/compare/{from_name}/{to_name}",
    response_model=PersonalityCompareResponse,
    summary="Compare personalities",
    description="Compare two personality configurations and return field-level differences.",
)
async def compare_personalities(from_name: str, to_name: str):
    try:
        from_config = await resolve_persona_config(from_name)
        to_config = await resolve_persona_config(to_name)
        if from_config is None:
            raise HTTPException(status_code=404, detail=f"Personality not found: {from_name}")
        if to_config is None:
            raise HTTPException(status_code=404, detail=f"Personality not found: {to_name}")
        from_data = from_config.to_dict()
        to_data = to_config.to_dict()
        from_model = PersonalityConfigModel.model_validate(from_data)
        to_model = PersonalityConfigModel.model_validate(to_data)
        diffs = _build_diffs(from_model.model_dump(), to_model.model_dump())

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


# ============ Bootstrap Dialogue Endpoints ============

@personality_config_router.post(
    "/bootstrap/init",
    response_model=PersonalityResponse,
    summary="Initialize bootstrap dialogue",
    description="Generate the persona opening line, persist it as a real chat message, and emit a notification.",
)
async def api_bootstrap_init(request: BootstrapInitRequest):
    try:
        import uuid as _uuid

        current_name = get_current_personality_name()
        persona_id = await _resolve_persona_id(current_name)
        bootstrap_svc = await _get_bootstrap_service()

        if not await bootstrap_svc.needs_bootstrap(current_name, persona_id=persona_id):
            return PersonalityResponse(
                success=True,
                message="Bootstrap already completed",
                data={"bootstrap_active": False, "opening": None},
            )

        opening = await bootstrap_svc.get_opening(current_name, persona_id=persona_id)
        if not opening:
            return PersonalityResponse(
                success=True,
                message="No opening available",
                data={"bootstrap_active": True, "opening": None},
            )

        turn_id = f"turn_bs_{_uuid.uuid4().hex[:12]}"
        try:
            await _persist_bootstrap_assistant_message(
                session_id=request.session_id,
                user_id=request.user_id,
                turn_id=turn_id,
                content=opening,
            )
        except RuntimeError as exc:
            # chat_store or other runtime bindings may not be ready yet
            # during early startup; return the opening anyway.
            logger.warning("Bootstrap opening not persisted (runtime not ready): %s", exc)

        return PersonalityResponse(
            success=True,
            message="Bootstrap opening injected",
            data={"bootstrap_active": True, "opening": opening},
        )
    except Exception as exc:
        logger.error("Bootstrap init failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_config_router.post(
    "/bootstrap/message",
    response_model=PersonalityResponse,
    summary="Send a bootstrap dialogue message",
    description="Exchange a message in the persona bootstrap (first-contact) dialogue. "
    "Both user and assistant messages are persisted as real chat turns.",
)
async def api_bootstrap_message(request: BootstrapMessageRequest):
    try:
        import time as _time
        import uuid as _uuid

        from ...core.runtime_bindings import require_chat_store

        current_name = get_current_personality_name()
        persona_id = await _resolve_persona_id(current_name)
        bootstrap_svc = await _get_bootstrap_service()

        if not await bootstrap_svc.needs_bootstrap(current_name, persona_id=persona_id):
            return PersonalityResponse(
                success=True,
                message="Bootstrap already completed",
                data={"reply": None, "is_complete": True},
            )

        # Persist user message as a real chat turn
        user_turn_id = f"turn_bs_{_uuid.uuid4().hex[:12]}"
        now_ms = int(_time.time() * 1000)
        try:
            chat_store = require_chat_store()
            await chat_store.create_user_turn(
                session_id=request.session_id,
                user_id=request.user_id,
                turn_id=user_turn_id,
                message_text=request.user_message,
                created_at_ms=now_ms,
            )
        except Exception as exc:
            logger.warning("Failed to persist bootstrap user turn: %s", exc)

        reply = await bootstrap_svc.reply(
            persona_name=current_name,
            user_id=request.user_id,
            session_id=request.session_id,
            user_message=request.user_message,
            history=request.history,
            persona_id=persona_id,
        )

        still_needs = await bootstrap_svc.needs_bootstrap(current_name, persona_id=persona_id)
        is_complete = not still_needs

        # Persist assistant reply as a real chat message + emit notification
        reply_turn_id = f"turn_bs_{_uuid.uuid4().hex[:12]}"
        try:
            await _persist_bootstrap_assistant_message(
                session_id=request.session_id,
                user_id=request.user_id,
                turn_id=reply_turn_id,
                content=reply,
            )
        except RuntimeError as exc:
            logger.warning("Bootstrap reply not persisted (runtime not ready): %s", exc)

        return PersonalityResponse(
            success=True,
            message="Bootstrap reply generated",
            data={"reply": reply, "is_complete": is_complete},
        )
    except Exception as exc:
        logger.error("Bootstrap message failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ============ Journal Reflection Endpoint ============

@personality_config_router.post(
    "/journal/reflect",
    response_model=PersonalityResponse,
    summary="Trigger a persona journal reflection",
    description="Generate a persona-perspective reflection entry and store it as a milestone.",
)
async def api_journal_reflect(request: JournalReflectRequest):
    try:
        persona_name = request.persona_name or get_current_personality_name()
        journal_svc = await _get_journal_service()

        entry = await journal_svc.generate_reflection(
            persona_name=persona_name,
            emotional_state=request.emotional_state,
            relationship=request.relationship,
            recent_milestones=request.recent_milestones,
        )

        if entry is None:
            return PersonalityResponse(
                success=False,
                message="Reflection generation failed",
                data=None,
            )

        return PersonalityResponse(
            success=True,
            message="Journal reflection generated",
            data={
                "milestone_id": entry.milestone_id,
                "content": entry.content,
                "timestamp": entry.timestamp,
            },
        )
    except Exception as exc:
        logger.error("Journal reflection failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
