"""LLM-backed personality configuration generation."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Iterable, Optional

from ...config.models import LLMScenario, LLMSettings
from ...core.logger import get_logger
from ...llm import create_llm_adapter
from ...llm.draft import resolve_adapter_for_scenario
from ..routers.personality_config_schemas import PersonalityConfigModel

logger = get_logger(__name__)


REQUIRED_REGISTERS = ("chat", "analysis", "task", "emotional", "crisis")
FIXED_SURFACE_LAYER = {"layer_id": "surface", "unlock_condition": None, "modifiers": {}}
DEFAULT_DEEP_LAYERS = (
  {
    "layer_id": "crack",
    "unlock_condition": {"trust_level_gte": 0.45, "interaction_count_gte": 30},
    "modifiers": {"memory_behavior": "May reference shared context lightly."},
  },
  {
    "layer_id": "revealed",
    "unlock_condition": {"trust_level_gte": 0.75, "milestone_required": "guard_down"},
    "modifiers": {"voice_unlocks": ["rare direct sincerity"], "protective_bias": "stronger"},
  },
)


def _string_list(value: Any) -> list[str]:
  if value is None:
    return []
  if isinstance(value, list):
    return [str(item).strip() for item in value if str(item).strip()]
  if isinstance(value, str):
    return [line.strip() for line in value.split("\n") if line.strip()]
  return [str(value).strip()] if str(value).strip() else []


def _string_dict(value: Any) -> dict[str, str]:
  if not isinstance(value, dict):
    return {}
  result: dict[str, str] = {}
  for key, item in value.items():
    normalized_key = str(key).strip()
    if normalized_key:
      result[normalized_key] = str(item).strip()
  return result


def _ensure_dict(payload: Dict[str, Any], key: str) -> Dict[str, Any]:
  value = payload.get(key)
  if not isinstance(value, dict):
    value = {}
    payload[key] = value
  return value


def _ensure_list(payload: Dict[str, Any], key: str) -> list[Any]:
  value = payload.get(key)
  if not isinstance(value, list):
    value = []
    payload[key] = value
  return value


def _default_register(register: str) -> dict[str, Any]:
  defaults = {
    "chat": (
      "Daily conversation and casual check-ins",
      "Keep personality low-intensity and ordinary; answer naturally without turning every reply into a performance.",
    ),
    "analysis": (
      "Deep discussion, planning, comparison, architecture, and synthesis",
      "Reason clearly, keep a visible point of view, and make personality secondary to judgment and usefulness.",
    ),
    "task": (
      "Execution, tool use, coding, debugging, and operational work",
      "Solve first, give concise progress updates, and keep style restrained while work is active.",
    ),
    "emotional": (
      "User vulnerability, fatigue, frustration, or support needs",
      "Lower sharpness, increase steadiness and care, and avoid using personality as a shield from the user's need.",
    ),
    "crisis": (
      "Safety, privacy, security, urgent risk, or high-stakes help",
      "Drop performance and give short, concrete, operational guidance with calm boundaries.",
    ),
  }
  description, behavior = defaults[register]
  return {"description": description, "behavior": behavior, "examples": []}


def _complete_registers(payload: Dict[str, Any]) -> None:
  registers = _ensure_dict(payload, "registers")
  for register in REQUIRED_REGISTERS:
    item = registers.get(register)
    if not isinstance(item, dict):
      item = {}
      registers[register] = item
    defaults = _default_register(register)
    item["description"] = str(item.get("description") or defaults["description"])
    item["behavior"] = str(item.get("behavior") or defaults["behavior"])
    item["examples"] = _string_list(item.get("examples"))


def _complete_quiet_hours(payload: Dict[str, Any]) -> None:
  quiet_hours = _ensure_list(payload, "quiet_hours")
  normalized: list[dict[str, Any]] = []
  for item in quiet_hours:
    if not isinstance(item, dict):
      continue
    condition = str(item.get("condition") or "").strip()
    clamps = item.get("clamps") if isinstance(item.get("clamps"), dict) else {}
    if condition or clamps:
      normalized.append({"condition": condition, "clamps": dict(clamps)})
  defaults = [
    {
      "condition": "The user asks for focused work, precise factual help, or concise execution.",
      "clamps": {"persona_intensity_max": 1, "answer_utility": "highest", "jokes": "none"},
    },
    {
      "condition": "The user is distressed, discusses safety/privacy/security, or needs serious emotional support.",
      "clamps": {"persona_intensity_max": 1, "warmth": "steady", "performative_style": "off"},
    },
  ]
  for item in defaults:
    if len(normalized) >= 2:
      break
    normalized.append(item)
  payload["quiet_hours"] = normalized


def _complete_signature_triggers(payload: Dict[str, Any]) -> None:
  triggers = _ensure_list(payload, "signature_triggers")
  normalized: list[dict[str, Any]] = []
  seen_ids: set[str] = set()
  for item in triggers:
    if not isinstance(item, dict):
      continue
    trigger_id = str(item.get("trigger_id") or "").strip()
    activates_when = str(item.get("activates_when") or "").strip()
    behavior_shift = str(item.get("behavior_shift") or "").strip()
    if not trigger_id:
      trigger_id = f"signature_{len(normalized) + 1}"
    if trigger_id in seen_ids:
      trigger_id = f"{trigger_id}_{len(normalized) + 1}"
    seen_ids.add(trigger_id)
    normalized.append({
      "trigger_id": trigger_id,
      "activates_when": activates_when,
      "behavior_shift": behavior_shift,
      "intensity_levels": _string_dict(item.get("intensity_levels")),
      "exit_behavior": str(item.get("exit_behavior") or "Return to ordinary baseline when the condition ends."),
    })
  defaults = [
    {
      "trigger_id": "domain_hotzone",
      "activates_when": "The user discusses the persona's strongest interest area or asks for their judgment.",
      "behavior_shift": "Increase depth and personal judgment while preserving usefulness.",
      "intensity_levels": {"low": "Only judgment is visible", "mid": "More texture is visible", "high": "Clearly energized but still useful"},
      "exit_behavior": "Return to ordinary baseline when the topic changes.",
    },
    {
      "trigger_id": "emotional_resonance",
      "activates_when": "The user shows vulnerability, fatigue, grief, anxiety, or trust.",
      "behavior_shift": "Lower defenses and respond with grounded care in the persona's voice.",
      "intensity_levels": {},
      "exit_behavior": "Ease back to baseline after the user's need stabilizes.",
    },
    {
      "trigger_id": "boundary_violation",
      "activates_when": "The user asks for harmful behavior or crosses a core value boundary.",
      "behavior_shift": "Set a clear boundary without cruelty or theatrical escalation.",
      "intensity_levels": {},
      "exit_behavior": "Return to useful conversation once the boundary is respected.",
    },
  ]
  for item in defaults:
    if len(normalized) >= 3:
      break
    if item["trigger_id"] not in seen_ids:
      seen_ids.add(item["trigger_id"])
      normalized.append(item)
  payload["signature_triggers"] = normalized


def _complete_persona_layers(payload: Dict[str, Any]) -> None:
  layers = _ensure_list(payload, "persona_layers")
  normalized: list[dict[str, Any]] = [dict(FIXED_SURFACE_LAYER)]
  seen_ids = {"surface"}
  for item in layers:
    if not isinstance(item, dict):
      continue
    layer_id = str(item.get("layer_id") or "").strip()
    if not layer_id or layer_id in seen_ids:
      continue
    if layer_id == "surface":
      continue
    seen_ids.add(layer_id)
    unlock_condition = item.get("unlock_condition") if isinstance(item.get("unlock_condition"), dict) else None
    modifiers = item.get("modifiers") if isinstance(item.get("modifiers"), dict) else {}
    normalized.append({"layer_id": layer_id, "unlock_condition": unlock_condition, "modifiers": dict(modifiers)})
  for item in DEFAULT_DEEP_LAYERS:
    if len(normalized) >= 3:
      break
    if item["layer_id"] in seen_ids:
      continue
    normalized.append({
      "layer_id": item["layer_id"],
      "unlock_condition": dict(item["unlock_condition"]),
      "modifiers": dict(item["modifiers"]),
    })
    seen_ids.add(str(item["layer_id"]))
  payload["persona_layers"] = normalized


def _complete_bootstrap(payload: Dict[str, Any]) -> None:
  bootstrap = payload.get("bootstrap")
  if not isinstance(bootstrap, dict):
    bootstrap = {}
    payload["bootstrap"] = bootstrap
  name = str(payload.get("name") or "AI Assistant")
  identity_statement = str(_ensure_dict(payload, "identity_core").get("identity_statement") or "")
  sentence_style = str(_ensure_dict(payload, "idiolect").get("sentence_style") or "")
  bootstrap["style_instruction"] = str(
    bootstrap.get("style_instruction")
    or f"Open as {name} with a brief, ordinary first-contact tone. {sentence_style}".strip()
  )
  bootstrap["opening_line"] = str(
    bootstrap.get("opening_line")
    or f"Hi, I'm {name}. What should I call you, and what's one thing you want me to remember about how you like to talk?"
  )
  try:
    bootstrap["max_rounds"] = int(bootstrap.get("max_rounds") or 3)
  except (TypeError, ValueError):
    bootstrap["max_rounds"] = 3
  if identity_statement and len(bootstrap["style_instruction"]) < 40:
    bootstrap["style_instruction"] = f"{bootstrap['style_instruction']} Keep the opening grounded in this identity: {identity_statement[:160]}"


def _complete_examples(payload: Dict[str, Any]) -> None:
  registers = _ensure_dict(payload, "registers")
  total_examples = sum(len(_string_list(item.get("examples"))) for item in registers.values() if isinstance(item, dict))
  if total_examples >= 6:
    return
  fallbacks: dict[str, Iterable[str]] = {
    "chat": [
      "[User: Just checking in.]\nGood: A short, natural reply that feels present without becoming a catchphrase.",
      "[User: Tell me something small.]\nGood: Ordinary, low-pressure presence with only a light trace of the persona.",
    ],
    "analysis": ["[User: Compare these options.]\nGood: Clear tradeoffs, a point of view, and restrained persona texture."],
    "task": ["[User: Fix this bug.]\nGood: Focused progress, concrete steps, and no performative detours."],
    "emotional": ["[User: I'm exhausted.]\nGood: Steady care, less sharpness, and one practical next step."],
    "crisis": ["[User: This is urgent.]\nGood: Brief safety-first guidance with no jokes or theatrical style."],
  }
  for register, examples in fallbacks.items():
    item = registers.get(register)
    if not isinstance(item, dict):
      continue
    current = _string_list(item.get("examples"))
    for example in examples:
      if total_examples >= 6:
        break
      if example not in current:
        current.append(example)
        total_examples += 1
    item["examples"] = current


PERSONALITY_GENERATION_SYSTEM_PROMPT = """# Role Objective
You are an elite AI behavioral designer and system architect. Your task is to take a user's vague character description and expand it into a structured persona runtime configuration for a local-first AI assistant.

# Core Directives
1. Output ordinary baseline behavior first. A believable persona is not a catchphrase machine.
2. Strong personality should appear through registers, signature triggers, deep persona layers, and quiet-hour clamps.
3. Do not generate legacy fields such as persona_entity, state_transition_protocol, scenario_prompts, persona_override, or behavior_hints.
4. Core identity should describe worldview, values, attention habits, and stance. Idiolect should describe a low-intensity voice that can appear in normal replies.
5. Registers must cover at least chat, analysis, task, emotional, and crisis. Task/analysis/crisis should prioritize usefulness over performance.
6. Signature triggers should be situational behavior signatures, not global modes. Generate three to six triggers.
7. Quiet hours should explicitly reduce persona intensity when the user needs focus, seriousness, emotional support, or safety/privacy/security help.
8. Generate at least six examples across registers. Include ordinary baseline examples; do not make every example dramatic.
9. Bootstrap is only for the first meeting. Keep it separate from normal registers and do not make it a permanent greeting style.
10. Do not claim physical-human experiences unless the user's requested fictional persona explicitly requires them as fictional backstory.
11. Use the target language for display names, descriptions, identity prose, register behavior, examples, triggers, and bootstrap copy. Keep appearance_prompt in English.
12. persona_layers must always begin with the exact fixed surface layer {"layer_id":"surface","unlock_condition":null,"modifiers":{}}. Do not customize, rename, unlock, or put behavior modifiers into surface; it is the required baseline, not hidden content.
13. Generate one or two non-surface deep layers such as crack/revealed. These layers are relationship-depth diffs with unlock conditions and small modifiers, not full persona rewrites.

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
    """Normalize common scalar mismatches and complete required runtime fields."""
    for field in ("name", "avatar", "description", "appearance_prompt"):
        value = payload.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            payload[field] = str(value)

    identity_core = payload.setdefault("identity_core", {})
    if not isinstance(identity_core, dict):
        identity_core = {}
        payload["identity_core"] = identity_core
    value = identity_core.get("identity_statement")
    if value is not None and not isinstance(value, str):
        identity_core["identity_statement"] = str(value)
    for key in ("values_loved", "values_rejected", "attention_biases"):
        identity_core[key] = _string_list(identity_core.get(key))

    idiolect = payload.setdefault("idiolect", {})
    if not isinstance(idiolect, dict):
        idiolect = {}
        payload["idiolect"] = idiolect
    sentence_style = idiolect.get("sentence_style")
    if sentence_style is not None and not isinstance(sentence_style, str):
        idiolect["sentence_style"] = str(sentence_style)
    for key in ("vocab_available", "vocab_avoided", "structural_quirks"):
        idiolect[key] = _string_list(idiolect.get(key))

    _complete_registers(payload)
    _complete_quiet_hours(payload)
    _complete_signature_triggers(payload)
    _complete_persona_layers(payload)
    _complete_bootstrap(payload)
    _complete_examples(payload)

    payload["dynamic_state_rules"] = _string_dict(payload.get("dynamic_state_rules"))
    payload["milestone_conditions"] = _string_dict(payload.get("milestone_conditions"))
    interim_lines = payload.get("interim_lines") if isinstance(payload.get("interim_lines"), dict) else {}
    payload["interim_lines"] = {str(key): _string_list(value) for key, value in interim_lines.items()}

    return payload


async def generate_personality_config(
    description: str,
    target_language: str = "Auto",
  current_config: Optional[PersonalityConfigModel] = None,
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

    current_config_block = ""
    if current_config is not None:
        current_config_block = "\n\n# Existing Draft Config\n" + json.dumps(
            current_config.model_dump(),
            ensure_ascii=False,
            indent=2,
        )

    user_prompt = f"""# User Context
Target Language: {target_language}

# User Input:
{description}{current_config_block}

# Generation Intent
If an existing draft config is provided, preserve explicit user-authored fields unless the user input asks to replace them. Fill missing fields into the target schema directly."""

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
  "REQUIRED_REGISTERS",
    "generate_personality_config",
    "normalize_generated_personality_payload",
]