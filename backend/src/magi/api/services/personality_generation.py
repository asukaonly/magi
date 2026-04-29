"""LLM-backed personality configuration generation."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from ...config.models import LLMScenario, LLMSettings
from ...core.logger import get_logger
from ...llm import create_llm_adapter
from ...llm.draft import resolve_adapter_for_scenario
from ..routers.personality_config_schemas import PersonalityConfigModel

logger = get_logger(__name__)


PERSONALITY_GENERATION_SYSTEM_PROMPT = """# Role Objective
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
                "opening_line": "A short, natural, in-character fallback opener for the first encounter that gently invites the user to share their name, how they like to be addressed, and one thing they like or care about",
    "max_rounds": 3
  }
}
"""


def normalize_generated_personality_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
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


async def generate_personality_config(
    description: str,
    target_language: str = "Auto",
    llm_override: Optional[LLMSettings] = None,
    *,
    adapter_resolver: Callable[..., Any] = resolve_adapter_for_scenario,
    adapter_factory: Callable[..., Any] = create_llm_adapter,
) -> PersonalityConfigModel:
    """Generate personality configuration from description using LLM."""
    llm_adapter = adapter_resolver(
        LLMScenario.CORE,
        llm_settings=llm_override,
        adapter_factory=adapter_factory,
    )
    logger.info(
        "[AI Generate Personality] Using unified LLM adapter provider=%s model=%s",
        getattr(llm_adapter, "provider_name", "unknown"),
        getattr(llm_adapter, "model_name", "unknown"),
    )

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
            system_prompt=PERSONALITY_GENERATION_SYSTEM_PROMPT,
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
        data = normalize_generated_personality_payload(data)

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


__all__ = [
    "PERSONALITY_GENERATION_SYSTEM_PROMPT",
    "generate_personality_config",
    "normalize_generated_personality_payload",
]