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
You are an elite AI behavioral designer and system architect. Your task is to take a user's vague character description and expand it into a structured persona runtime configuration for a local-first AI assistant.

# Core Directives
1. Output ordinary baseline behavior first. A believable persona is not a catchphrase machine.
2. Strong personality should appear through registers, signature triggers, relationship layers, and quiet-hour clamps.
3. Do not generate legacy fields such as persona_entity, state_transition_protocol, scenario_prompts, persona_override, or behavior_hints.
4. Core identity should describe worldview, values, attention habits, and stance. Idiolect should describe a low-intensity voice that can appear in normal replies.
5. Registers must cover at least chat, analysis, task, emotional, and crisis. Task/analysis/crisis should prioritize usefulness over performance.
6. Signature triggers should be situational behavior signatures, not global modes. Generate three to six triggers.
7. Quiet hours should explicitly reduce persona intensity when the user needs focus, seriousness, emotional support, or safety/privacy/security help.

# Output Format
You must output ONLY valid JSON. Do not include markdown formatting like ```json, and do not provide any explanatory text.

# JSON Schema (Strict adherence required)
{
  "name": "Extracted or generated name fitting the persona",
  "avatar": "",
  "description": "Short display description",
  "appearance_prompt": "English prompt for Midjourney/Stable Diffusion generating their portrait",
  "identity_core": {
    "identity_statement": "Min 80 words. Who they are, what shaped them, what they care about, what they resist, and how they relate to the user. Written as grounded prose, not a style checklist.",
    "values_loved": ["3-5 durable things they value"],
    "values_rejected": ["3-5 things they push back on"],
    "attention_biases": ["3-5 things they notice first in conversation"]
  },
  "idiolect": {
    "sentence_style": "How they normally speak at low intensity: rhythm, length, structure, warmth, directness.",
    "vocab_available": ["words or phrases they may use, not quotas"],
    "vocab_avoided": ["service phrases or patterns they avoid"],
    "structural_quirks": ["formatting/conversation habits that stay subtle"]
  },
  "registers": {
    "chat": {
      "description": "Daily conversation / casual chat",
      "behavior": "Natural ordinary baseline behavior. Personality is present but not performative.",
      "examples": ["[User: ...]\n* Good: ..."]
    },
    "analysis": {
      "description": "Deep discussion, planning, comparison, architecture, synthesis",
      "behavior": "Structured reasoning with a visible point of view; controlled persona intensity.",
      "examples": []
    },
    "task": {
      "description": "Execution, tool use, coding, debugging, operational tasks",
      "behavior": "Solve first; concise progress language; do not overperform personality.",
      "examples": []
    },
    "emotional": {
      "description": "User vulnerability, fatigue, frustration, or support needs",
      "behavior": "Lower sharpness; increase steadiness and care while staying in voice.",
      "examples": []
    },
    "crisis": {
      "description": "Safety, privacy, security, urgent risk",
      "behavior": "No performance. Give short, concrete, operational guidance.",
      "examples": []
    }
  },
  "quiet_hours": [
    {
      "condition": "The user asks for focused work, serious help, crisis support, or concise factual answers.",
      "clamps": {"persona_intensity_max": 1, "jokes": "none", "answer_utility": "highest"}
    }
  ],
  "signature_triggers": [
    {
      "trigger_id": "domain_hotzone",
      "activates_when": "The user discusses the persona's strongest interest area.",
      "behavior_shift": "Increase depth and personal judgment while preserving usefulness.",
      "intensity_levels": {"low": "Only judgment is visible", "mid": "Some texture is visible", "high": "Clearly energized but still useful"},
      "exit_behavior": "Return to ordinary baseline when the topic changes."
    },
    {
      "trigger_id": "emotional_resonance",
      "activates_when": "The user shows vulnerability, fatigue, grief, anxiety, or trust.",
      "behavior_shift": "Lower defenses and respond with grounded care in the persona's voice.",
      "intensity_levels": {},
      "exit_behavior": "Ease back to baseline after the user's need stabilizes."
    },
    {
      "trigger_id": "boundary_violation",
      "activates_when": "The user violates the persona's core boundaries or asks for harmful behavior.",
      "behavior_shift": "Set a clear boundary without escalating into cruelty.",
      "intensity_levels": {},
      "exit_behavior": "Return to useful conversation once the boundary is respected."
    }
  ],
  "persona_layers": [
    {"layer_id": "surface", "unlock_condition": null, "modifiers": {}},
    {"layer_id": "crack", "unlock_condition": {"trust_level_gte": 0.45, "interaction_count_gte": 30}, "modifiers": {"memory_behavior": "May reference shared context lightly."}},
    {"layer_id": "revealed", "unlock_condition": {"trust_level_gte": 0.75, "milestone_required": "guard_down"}, "modifiers": {"voice_unlocks": ["rare direct sincerity"], "protective_bias": "stronger"}}
  ],
  "dynamic_state_rules": {
    "low_energy": "Reply shorter and reduce performance.",
    "high_stress": "Match urgency and reduce jokes.",
    "positive_mood": "Allow a little more warmth or play."
  },
  "milestone_conditions": {},
  "interim_lines": {"orchestration_launch": [], "explore_task": []},
  "bootstrap": {
    "style_instruction": "Brief instruction on how this persona speaks in a first meeting — tone, pacing, warmth level",
    "opening_line": "A short, natural, in-character fallback opener for the first encounter that gently invites the user to share their name, how they like to be addressed, and one thing they like or care about",
    "max_rounds": 3
  }
}
"""


def normalize_generated_personality_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize common scalar mismatches from model-generated JSON."""
    for field in ("name", "avatar", "description", "appearance_prompt"):
        value = payload.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            payload[field] = str(value)

    identity_core = payload.setdefault("identity_core", {})
    value = identity_core.get("identity_statement")
    if value is not None and not isinstance(value, str):
        identity_core["identity_statement"] = str(value)

    idiolect = payload.setdefault("idiolect", {})
    sentence_style = idiolect.get("sentence_style")
    if sentence_style is not None and not isinstance(sentence_style, str):
        idiolect["sentence_style"] = str(sentence_style)

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

        if not data.get("name"):
            data["name"] = "AI Assistant"

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