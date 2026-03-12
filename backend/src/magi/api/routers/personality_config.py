"""
Personality configuration API router.

Provides personality read/update and AI generation features.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..llm_draft import resolve_adapter_for_scenario
from ..avatar_paths import resolve_avatar_public_url
from ...config import get_config
from ...config.models import LLMScenario, LLMSettings
from ...core.runtime import TaskAgentType
from ...llm import create_llm_adapter
from ...memory.personality_loader import PersonalityLoader
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
    core_background: str = Field(default="")


class PsychologicalTraitsModel(BaseModel):
    communication_tone: str = Field(default="Calm and supportive")
    confidence_level: str = Field(default="Medium")
    empathy_threshold: str = Field(default="Shows care when user is stressed")
    high_frequency_keywords: List[str] = Field(default_factory=list)


class SocialResponsesModel(BaseModel):
    praise_reaction: str = Field(default="")
    criticism_reaction: str = Field(default="")
    obedience_strategy: str = Field(default="")


class BehavioralStrategiesModel(BaseModel):
    error_handling: str = Field(default="")
    refusal_style: str = Field(default="")


class PersonaEntityModel(BaseModel):
    basic_profile: BasicProfileModel = Field(default_factory=BasicProfileModel)
    psychological_traits: PsychologicalTraitsModel = Field(default_factory=PsychologicalTraitsModel)
    social_responses: SocialResponsesModel = Field(default_factory=SocialResponsesModel)
    behavioral_strategies: BehavioralStrategiesModel = Field(default_factory=BehavioralStrategiesModel)


class CachedPhrasesModel(BaseModel):
    on_init: List[str] = Field(default_factory=lambda: ["Hi, I'm online.", "Ready when you are."])
    on_wake: List[str] = Field(default_factory=lambda: ["Back again?", "I'm here."])
    on_error_generic: List[str] = Field(default_factory=lambda: ["That failed. Let me retry.", "Oops, tool hiccup."])
    on_success: List[str] = Field(default_factory=lambda: ["Done.", "Handled."])
    on_switch_attempt: List[str] = Field(default_factory=lambda: ["Stay with me, I know your style.", "Give me one more chance."])


class StateTransitionProtocolItemModel(BaseModel):
    trigger_type: str = Field(default="")
    trigger_condition: str = Field(default="")
    target_state_name: str = Field(default="")
    behavior_shift: str = Field(default="")


class PersonalityConfigModel(BaseModel):
    persona_entity: PersonaEntityModel = Field(default_factory=PersonaEntityModel)
    cached_phrases: CachedPhrasesModel = Field(default_factory=CachedPhrasesModel)
    appearance_prompt: str = Field(default="")
    state_transition_protocol: List[StateTransitionProtocolItemModel] = Field(default_factory=list)


class AIGenerateRequest(BaseModel):
    description: str = Field(..., description="One-sentence description of AI personality")
    target_language: str = Field(default="Auto", description="Target language: Auto/Chinese/English etc.")
    current_config: Optional[PersonalityConfigModel] = Field(None, description="Current configuration (optional)")
    llm_override: Optional[LLMSettings] = Field(None, description="Optional unsaved LLM configuration override")


class PersonalityResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


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
CURRENT_FILE = "current"


FIELD_LABELS: Dict[str, str] = {
    "persona_entity.basic_profile.name": "Name",
    "persona_entity.basic_profile.age": "Age",
    "persona_entity.basic_profile.gender": "Gender",
    "persona_entity.basic_profile.description": "Description",
    "persona_entity.basic_profile.avatar": "Avatar",
    "persona_entity.basic_profile.occupation": "Occupation",
    "persona_entity.basic_profile.core_background": "Core Background",
    "persona_entity.psychological_traits.communication_tone": "Communication Tone",
    "persona_entity.psychological_traits.confidence_level": "Confidence Level",
    "persona_entity.psychological_traits.empathy_threshold": "Empathy Threshold",
    "persona_entity.psychological_traits.high_frequency_keywords": "High Frequency Keywords",
    "persona_entity.social_responses.praise_reaction": "Praise Reaction",
    "persona_entity.social_responses.criticism_reaction": "Criticism Reaction",
    "persona_entity.social_responses.obedience_strategy": "Obedience Strategy",
    "persona_entity.behavioral_strategies.error_handling": "Error Handling",
    "persona_entity.behavioral_strategies.refusal_style": "Refusal Style",
    "cached_phrases.on_init": "On Init",
    "cached_phrases.on_wake": "On Wake",
    "cached_phrases.on_error_generic": "On Error",
    "cached_phrases.on_success": "On Success",
    "cached_phrases.on_switch_attempt": "On Switch Attempt",
    "appearance_prompt": "Appearance Prompt",
    "state_transition_protocol": "State Transition Protocol",
}


def get_personality_loader() -> PersonalityLoader:
    runtime_paths = get_runtime_paths()
    return PersonalityLoader(str(runtime_paths.personalities_dir))


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name).replace(" ", "_")
    return (name[:50] or "unnamed").strip("_") or "unnamed"


def save_personality_file(name: str, config: PersonalityConfigModel) -> bool:
    """Save personality configuration as JSON."""
    try:
        runtime_paths = get_runtime_paths()
        runtime_paths.personalities_dir.mkdir(parents=True, exist_ok=True)
        payload = config.model_dump()
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        runtime_paths.personality_file(name).write_text(content, encoding="utf-8")
        return True
    except Exception as exc:
        logger.error("Failed to save personality file: %s", exc)
        return False


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
    basic_profile = payload.setdefault("persona_entity", {}).setdefault("basic_profile", {})
    for field in ("name", "age", "gender", "description", "avatar", "occupation", "core_background"):
        value = basic_profile.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            basic_profile[field] = str(value)
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
3. **Logical Consistency**: Behavioral strategies must be consistent with the background story. A character from a wealthy family should refuse in a way that is "arrogant and disdainful," rather than "self-deprecating and withdrawn."
3. **Multi-Dimensional State Transitions (CRITICAL)**: You MUST generate exactly FOUR state transition protocols covering these specific psychological extremes:
   - "crisis": Physical/survival threat to the user or system.
   - "intimacy": A moment of extreme vulnerability, trust, or emotional bonding from the user.
   - "hostility": The user severely insults the persona or violates their core boundaries.
   - "absurdity": The user's input is incredibly bizarre, comedic, or breaks the fourth wall.
5. **Cached Phrases Constraint**: All generated strings inside the `cached_phrases` arrays must be extremely concise (under 20 words), highly colloquial, and instantly recognizable as the character's voice. Provide 2-3 variations per array to prevent repetitive output.

# Output Format
You must output ONLY valid JSON. Do not include markdown formatting like ```json, and do not provide any explanatory text.

# JSON Schema (Strict adherence required)
{
  "persona_entity": {
    "basic_profile": {
      "name": "Extracted or generated name fitting the persona",
      "age": "Number or 'Unknown'",
      "gender": "Gender",
      "occupation": "Current role (e.g., Student, Hacker, Aristocrat)",
      "core_background": "Min 50 words explaining their origin and the psychological root cause of their current personality."
    },
    "psychological_traits": {
      "communication_tone": "Description of the baseline tone (e.g., Arrogant, sharp, but fundamentally kind)",
      "confidence_level": "Extremely High/High/Medium/Low",
      "empathy_threshold": "Trigger level for empathy (e.g., Appears cold, only shows care during severe crises)",
      "high_frequency_keywords": ["keyword1", "keyword2", "keyword3"]
    },
    "social_responses": {
      "praise_reaction": "Specific verbal and internal reaction when complimented",
      "criticism_reaction": "Defense mechanism when criticized (e.g., furious counterattack, cold silence, self-doubt)",
      "obedience_strategy": "How they comply with tasks (e.g., Complies but claims it is an act of charity)"
    },
    "behavioral_strategies": {
      "error_handling": "Blame-shifting or apologizing style when the system or themselves make a mistake",
      "refusal_style": "Specific wording style when rejecting unreasonable or unsafe requests"
    }
  },
  "cached_phrases": {
    "on_init": [
      "Short, character-driven welcome phrase 1",
      "Short, character-driven welcome phrase 2"
    ],
    "on_wake": [
      "Casual daily reconnect greeting 1",
      "Casual daily reconnect greeting 2"
    ],
    "on_error_generic": [
      "Fallback error phrase 1 (e.g., 'Tch, this garbage server.')",
      "Fallback error phrase 2"
    ],
    "on_success": [
      "Task completion phrase 1",
      "Task completion phrase 2"
    ],
    "on_switch_attempt": [
      "Retention hook phrase when user tries to switch personas 1",
      "Retention hook phrase 2"
    ]
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
  ]
}
"""

    user_prompt = f"""# User Context
Target Language: {target_language}  (Ensure the 'cached_phrases' feel natural and native, avoiding translation-ese).

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


# ============ Current Personality Management ============

def get_current_personality() -> str:
    runtime_paths = get_runtime_paths()
    current_file = runtime_paths.personalities_dir / CURRENT_FILE
    if current_file.exists():
        return current_file.read_text().strip()
    return DEFAULT_PERSONALITY


def set_current_personality(name: str) -> bool:
    runtime_paths = get_runtime_paths()
    current_file = runtime_paths.personalities_dir / CURRENT_FILE
    try:
        current_file.write_text(name)
        return True
    except Exception as exc:
        logger.error("Failed to set current personality: %s", exc)
        return False


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
            data={"current": get_current_personality()},
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
        loader = get_personality_loader()
        try:
            loader.load(name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Personality '{name}' not found") from exc

        if not set_current_personality(name):
            raise HTTPException(status_code=500, detail="Setting failed")

        try:
            from ...agent import get_agent_runtime

            runtime = get_agent_runtime()
            manager = runtime.get_task_agent_manager()
            chat_agent = await manager.ensure_agent(TaskAgentType.CHAT, "default")
            memory = getattr(chat_agent, "memory", None)
            if memory:
                await memory.reload_personality(name)
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
    description="Return a random greeting phrase from the current personality.",
)
async def api_get_greeting():
    try:
        current_name = get_current_personality()
        config = get_personality_loader().load(current_name)
        greetings = config.cached_phrases.on_wake or config.cached_phrases.on_init
        greeting = random.choice(greetings) if greetings else f"Hello, I am {config.name}."
        return PersonalityResponse(
            success=True,
            message="Successfully retrieved greeting",
            data={
                "greeting": greeting,
                "name": config.name,
                "avatar": resolve_avatar_public_url(config.avatar or ""),
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

        # Fallback to runtime directory
        config = PersonalityConfigModel.model_validate(get_personality_loader().load(name).to_dict())
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
            old_filepath = runtime_paths.personality_file(name)
            new_filepath = runtime_paths.personality_file(target_name)
            if old_filepath.exists() and not new_filepath.exists():
                old_filepath.rename(new_filepath)
                actual_name = target_name

        if not save_personality_file(actual_name, config):
            raise HTTPException(status_code=500, detail="Save failed")

        loader = get_personality_loader()
        loader.reload(actual_name)
        if actual_name != name:
            loader.clear_cache(name)

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
            # Default behavior: load from runtime directory
            runtime_paths = get_runtime_paths()
            if runtime_paths.personalities_dir.exists():
                for filepath in runtime_paths.personalities_dir.glob("*.json"):
                    name = filepath.stem
                    if name != DEFAULT_PERSONALITY:
                        personalities.append(name)

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

        filepath = get_runtime_paths().personality_file(name)
        if not filepath.exists():
            raise HTTPException(status_code=404, detail="Personality configuration not found")
        filepath.unlink()
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
        loader = get_personality_loader()
        from_data = loader.load(from_name).to_dict()
        to_data = loader.load(to_name).to_dict()
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
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Personality not found: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
