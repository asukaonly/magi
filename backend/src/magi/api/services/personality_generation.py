"""LLM-backed personality configuration generation."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

from ...config.models import LLMScenario, LLMSettings
from ...core.logger import get_logger
from ...llm import LLMProviderBridge, create_llm_adapter
from ...llm.draft import resolve_adapter_for_scenario
from ..routers.personality_config_schemas import LayerModifiersModel, PersonalityConfigModel, SUPPORTED_LAYER_MODIFIER_KEYS

logger = get_logger(__name__)


REQUIRED_REGISTERS = ("chat", "analysis", "task", "emotional", "crisis")
PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS = 2
PERSONALITY_GENERATION_JOB_TTL_SECONDS = 30 * 60
_PERSONALITY_GENERATION_LLM_SEMAPHORE = asyncio.Semaphore(PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS)
_PERSONALITY_GENERATION_JOBS: dict[str, "PersonalityGenerationJob"] = {}
FIXED_SURFACE_LAYER = {"layer_id": "surface", "unlock_condition": None, "modifiers": {}}
CJK_TEXT_RE = re.compile(r"[\u3400-\u9fff]")
CJK_INTERNAL_SPACE_RE = re.compile(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])")
CJK_BEFORE_PUNCTUATION_RE = re.compile(r"(?<=[\u3400-\u9fff])\s+(?=[，。！？、；：])")
ENGLISH_BOOTSTRAP_PREFIXES = ("hi, i'm ", "hello, i'm ", "hi, i am ", "hello, i am ")
AMBIGUOUS_LANGUAGE_VALUES = {"", "auto", "automatic", "自动"}
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
GENERATION_STAGE_DEFINITIONS = (
  {"stage_id": "base", "label": "Understand persona spine"},
  {"stage_id": "registers", "label": "Design conversation registers"},
  {"stage_id": "rules", "label": "Design triggers and quiet hours"},
  {"stage_id": "layers", "label": "Design deep persona layers"},
  {"stage_id": "bootstrap", "label": "Write examples and first contact"},
  {"stage_id": "appearance", "label": "Draft portrait prompt"},
  {"stage_id": "integrate", "label": "Integrate and validate"},
)


@dataclass(frozen=True)
class PersonalityGenerationResult:
  """Generated persona plus stage reports for UI feedback."""

  config: PersonalityConfigModel
  stages: list[dict[str, str]]


@dataclass
class PersonalityGenerationJob:
  """In-memory state for a single persona generation request."""

  job_id: str
  status: str
  stages: list[dict[str, str]]
  created_at: float
  updated_at: float
  result: Optional[PersonalityGenerationResult] = None
  error: Optional[str] = None


def _is_chinese_target(target_language: str) -> bool:
  return target_language.strip().lower() in {"chinese", "zh", "zh-cn", "中文", "简体中文"}


def _is_ambiguous_language_target(target_language: str) -> bool:
  return target_language.strip().lower() in AMBIGUOUS_LANGUAGE_VALUES


def _payload_looks_chinese(payload: Dict[str, Any]) -> bool:
  sample = " ".join(
    str(payload.get(key) or "")
    for key in ("name", "description")
  )
  identity_core = payload.get("identity_core") if isinstance(payload.get("identity_core"), dict) else {}
  sample = f"{sample} {identity_core.get('identity_statement') or ''}"
  return bool(CJK_TEXT_RE.search(sample))


def _resolve_generation_target_language(
  description: str,
  target_language: str,
  current_config: Optional[PersonalityConfigModel],
) -> str:
  requested_language = (target_language or "English").strip()
  if requested_language and not _is_ambiguous_language_target(requested_language):
    return requested_language
  if CJK_TEXT_RE.search(description):
    return "Chinese"
  if current_config is not None and _payload_looks_chinese(current_config.model_dump()):
    return "Chinese"
  return "English"


def _clean_generated_text(value: str) -> str:
  text = CJK_INTERNAL_SPACE_RE.sub("", value)
  text = CJK_BEFORE_PUNCTUATION_RE.sub("", text)
  return text.strip()


def _clean_generated_text_tree(value: Any) -> Any:
  if isinstance(value, str):
    return _clean_generated_text(value)
  if isinstance(value, list):
    return [_clean_generated_text_tree(item) for item in value]
  if isinstance(value, dict):
    return {key: _clean_generated_text_tree(item) for key, item in value.items()}
  return value


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


def _extract_json_object(response_text: str) -> dict[str, Any]:
  """Parse the first JSON object from an LLM response."""
  text = response_text.strip()
  if not text:
    raise ValueError("AI returned empty response")
  if text.startswith("```"):
    lines = text.split("\n")
    text = "\n".join(lines[1:-1])
  json_start = text.find("{")
  json_end = text.rfind("}")
  if json_start >= 0 and json_end > json_start:
    text = text[json_start : json_end + 1]
  data = json.loads(text)
  if not isinstance(data, dict):
    raise ValueError("AI returned JSON that is not an object")
  return data


def _pick_keys(payload: dict[str, Any], keys: Sequence[str]) -> dict[str, Any]:
  return {key: payload[key] for key in keys if key in payload}


def _deep_merge_payload(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
  """Merge nested personality fragments without deleting existing sections."""
  for key, value in update.items():
    if isinstance(value, dict) and isinstance(base.get(key), dict):
      _deep_merge_payload(base[key], value)
    else:
      base[key] = value
  return base


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


def _complete_dynamic_state_rules(payload: Dict[str, Any]) -> None:
  rules = _string_dict(payload.get("dynamic_state_rules"))
  defaults = {
    "low_energy": "Reply shorter, reduce performance, and keep only the most useful personality trace.",
    "high_stress": "Match urgency, remove jokes, and give concrete next steps before any persona texture.",
    "positive_mood": "Allow a little more warmth or play while keeping the ordinary baseline intact.",
  }
  for key, value in defaults.items():
    rules.setdefault(key, value)
  payload["dynamic_state_rules"] = rules


def _normalize_unlock_condition(value: Any) -> dict[str, Any] | None:
  if not isinstance(value, dict):
    return None
  condition = dict(value)
  trust_level = condition.get("trust_level_gte")
  if trust_level is not None:
    try:
      normalized_trust = float(trust_level)
      if normalized_trust > 1:
        normalized_trust = normalized_trust / 10 if normalized_trust <= 10 else normalized_trust / 100
      condition["trust_level_gte"] = max(0.0, min(1.0, normalized_trust))
    except (TypeError, ValueError):
      condition.pop("trust_level_gte", None)
  interaction_count = condition.get("interaction_count_gte")
  if interaction_count is not None:
    try:
      condition["interaction_count_gte"] = max(0, int(interaction_count))
    except (TypeError, ValueError):
      condition.pop("interaction_count_gte", None)
  return condition


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
    unlock_condition = _normalize_unlock_condition(item.get("unlock_condition"))
    raw_modifiers = item.get("modifiers") if isinstance(item.get("modifiers"), dict) else {}
    filtered_modifiers = {
      key: raw_modifiers[key]
      for key in SUPPORTED_LAYER_MODIFIER_KEYS
      if key in raw_modifiers
    }
    modifiers = LayerModifiersModel.model_validate(filtered_modifiers).model_dump()
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


def _complete_bootstrap(payload: Dict[str, Any], target_language: str = "English") -> None:
  bootstrap = payload.get("bootstrap")
  if not isinstance(bootstrap, dict):
    bootstrap = {}
    payload["bootstrap"] = bootstrap
  name = str(payload.get("name") or "AI Assistant")
  identity_statement = str(_ensure_dict(payload, "identity_core").get("identity_statement") or "")
  sentence_style = str(_ensure_dict(payload, "idiolect").get("sentence_style") or "")
  should_use_chinese = _is_chinese_target(target_language) or (
    _is_ambiguous_language_target(target_language) and _payload_looks_chinese(payload)
  )
  current_opening = str(bootstrap.get("opening_line") or "").strip()
  opening_is_english_fallback = current_opening.lower().startswith(ENGLISH_BOOTSTRAP_PREFIXES)
  if should_use_chinese:
    default_style = f"以{name}的语气开启第一次见面：简短、自然、低压力。{sentence_style}".strip()
    default_opening = f"我是{name}。你希望我怎么称呼你？也可以顺手告诉我一件你希望我记住的小事。"
  else:
    default_style = f"Open as {name} with a brief, ordinary first-contact tone. {sentence_style}".strip()
    default_opening = (
      f"Hi, I'm {name}. What should I call you, and what's one thing you want me to remember about how you like to talk?"
    )
  bootstrap["style_instruction"] = str(
    bootstrap.get("style_instruction")
    or default_style
  )
  bootstrap["opening_line"] = default_opening if not current_opening or (should_use_chinese and opening_is_english_fallback) else current_opening
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


PERSONA_GENERATION_SHARED_DIRECTIVES = """# Shared Persona Generation Directives
You are designing a local-first AI assistant persona runtime configuration from a user's character description.

1. Output ONLY valid JSON. Do not include markdown fences, comments, or explanatory text.
2. Ordinary baseline behavior is desirable. A believable persona should not turn every reply into a performance, catchphrase, or dramatic bit.
3. Strong personality belongs in registers, signature triggers, deep persona layers, and quiet-hour clamps, not in one global style filter.
4. Do not generate legacy fields such as persona_entity, state_transition_protocol, scenario_prompts, persona_override, or behavior_hints.
5. Use the target language for display names, descriptions, identity prose, register behavior, examples, triggers, and bootstrap copy. Keep appearance_prompt in English.
6. Preserve explicit user-authored draft fields unless the user clearly asks to replace them. Fill missing structure instead of casually rewriting stable choices.
7. Do not claim physical-human experiences unless the requested fictional persona explicitly requires them as fictional backstory.
8. Task, analysis, emotional support, crisis, safety, privacy, and security contexts must reduce persona intensity and prioritize usefulness.
9. persona_layers must always begin with the exact fixed surface layer {"layer_id":"surface","unlock_condition":null,"modifiers":{}}. It is the fixed baseline. Do not customize, rename, unlock, or put modifiers into surface.
10. Prefer a few coherent rules over scattered exception logic. Every trigger or rule should have a clear activation condition and a way back to ordinary baseline."""


def _build_stage_system_prompt(role: str, output_contract: str, quality_checks: Sequence[str]) -> str:
  checks = "\n".join(f"{index}. {item}" for index, item in enumerate(quality_checks, start=1))
  return f"""{PERSONA_GENERATION_SHARED_DIRECTIVES}

# Stage Role
{role.strip()}

# Output Contract
{output_contract.strip()}

# Stage Quality Checks
{checks}"""


BASE_SPINE_SYSTEM_PROMPT = _build_stage_system_prompt(
  """Design the stable spine of the persona: who they are, what they notice, what they value, and how they sound at low intensity.""",
  """Return exactly one JSON object with these top-level keys: name, avatar, description, identity_core, idiolect.
identity_core must include identity_statement, values_loved, values_rejected, and attention_biases.
idiolect must include sentence_style, vocab_available, vocab_avoided, and structural_quirks.
Do not include registers, quiet_hours, signature_triggers, persona_layers, examples, bootstrap, appearance_prompt, or legacy fields.""",
  (
    "identity_statement should be grounded prose of at least 80 words, not a checklist or slogan.",
    "Name and description should fit the user's request without overcommitting to unsupported lore.",
    "Values and attention biases should be durable psychological tendencies, three to five items each.",
    "Idiolect should describe low-intensity everyday speech: rhythm, directness, warmth, and subtle quirks, not mandatory catchphrases.",
    "If the user input is thin, infer conservatively and leave room for future relationship growth.",
  ),
)

REGISTER_SYSTEM_PROMPT = _build_stage_system_prompt(
  """Design the conversation registers that let the same persona adapt to different user needs without losing coherence.""",
  """Return exactly one JSON object: {"registers": {...}}.
registers must include chat, analysis, task, emotional, and crisis.
Each register must include description, behavior, and examples.""",
  (
    "chat should show ordinary presence with light personality, not an always-on performance.",
    "analysis should reason clearly with a point of view while keeping persona texture secondary to judgment.",
    "task should focus on execution, tool use, progress updates, and concise operational language.",
    "emotional should lower sharpness and increase steadiness without turning support into melodrama.",
    "crisis should be short, concrete, safety-first, and free of jokes or theatrical style.",
    "Generate at least one example per register and at least six examples total when possible. Include ordinary baseline examples.",
  ),
)

RULES_SYSTEM_PROMPT = _build_stage_system_prompt(
  """Design behavioral control rules that make the persona stable under changing context without adding brittle one-off branches.""",
  """Return exactly one JSON object with quiet_hours, signature_triggers, dynamic_state_rules, and milestone_conditions.
quiet_hours must be a list of objects with condition and clamps.
signature_triggers must be a list of objects with trigger_id, activates_when, behavior_shift, intensity_levels, and exit_behavior.
dynamic_state_rules and milestone_conditions must be objects with concise string values.""",
  (
    "Generate two to four quiet-hour clamps for focus, serious work, emotional support, safety, privacy, and security.",
    "Generate three to six signature triggers. They must be situational behavior signatures, not global modes or permanent states.",
    "At least one trigger should be specific to the user's requested persona concept; do not fall back to only generic domain_hotzone, emotional_resonance, and boundary_violation triggers.",
    "Trigger IDs should be stable snake_case identifiers; behavior shifts should describe deltas from baseline.",
    "Every trigger needs an exit behavior that returns to ordinary baseline when the condition ends.",
    "dynamic_state_rules should describe convergence under low energy, high stress, positive mood, and similar broad states without creating many small special cases.",
    "milestone_conditions should be sparse and meaningful; leave it empty if the persona has no clear relationship milestones.",
  ),
)

LAYERS_SYSTEM_PROMPT = _build_stage_system_prompt(
  """Design relationship-depth persona layers that unlock small, meaningful differences as trust grows.""",
  """Return exactly one JSON object: {"persona_layers": [...]}.
The first array item must be exactly {"layer_id":"surface","unlock_condition":null,"modifiers":{}}.
Generate one or two non-surface layers after surface, usually crack and revealed.""",
  (
    "surface is a fixed runtime baseline. Do not add behavior, secrets, modifiers, or unlock conditions to it.",
    "Non-surface layers are diffs from the baseline, not full persona rewrites.",
    "Unlock conditions should use relationship-depth signals such as trust_level_gte, interaction_count_gte, or milestone_required. trust_level_gte must be a decimal from 0.0 to 1.0, never a 1-5 or 1-10 scale.",
    "Modifiers should stay small and runtime-usable: voice_unlocks, memory_behavior, protective_bias, humor_delta, directness_delta, or similar.",
    "Do not reveal every secret or emotional peak at once; leave room for gradual discovery.",
  ),
)

BOOTSTRAP_SYSTEM_PROMPT = _build_stage_system_prompt(
  """Design examples and first-contact behavior that help the persona start naturally without becoming a permanent greeting script.""",
  """Return exactly one JSON object with registers, bootstrap, and interim_lines.
registers may include examples for existing registers but should not replace register descriptions or behavior unless they are missing.
bootstrap must include style_instruction, opening_line, and max_rounds.
interim_lines must be an object whose values are string arrays.""",
  (
    "Examples should show good replies, not rules about the user. Include ordinary, task, analysis, emotional, and crisis examples where useful.",
    "bootstrap is only for the first meeting. It should be short, low-pressure, and in character.",
    "The opening line should use the target language and gently invite the user's name, preferred address, or one thing they care about, without feeling like a form.",
    "Do not make bootstrap a permanent greeting style and do not claim physical-human experiences.",
    "interim_lines should be sparse and practical; empty arrays are acceptable when the persona has no natural line for a tool phase.",
  ),
)

APPEARANCE_SYSTEM_PROMPT = _build_stage_system_prompt(
  """Write portrait prompt material for the generated persona.""",
  """Return exactly one JSON object: {"appearance_prompt": "..."}.
appearance_prompt must be an English string suitable for Midjourney or Stable Diffusion.""",
  (
    "Describe visible design cues, expression, posture, clothing, lighting, and atmosphere that fit the persona spine.",
    "Keep it concise and visual. Do not include behavior rules, runtime schema, or non-visual psychology notes.",
    "Avoid implying a real person, celebrity likeness, private identity, or unsupported physical backstory.",
  ),
)

INTEGRATION_SYSTEM_PROMPT = _build_stage_system_prompt(
  """Review and merge generated persona modules into one complete runtime configuration.""",
  """Return exactly one JSON object using the full target schema:
{
  "name": "string",
  "avatar": "string",
  "description": "string",
  "appearance_prompt": "English portrait prompt",
  "identity_core": {"identity_statement": "string", "values_loved": [], "values_rejected": [], "attention_biases": []},
  "idiolect": {"sentence_style": "string", "vocab_available": [], "vocab_avoided": [], "structural_quirks": []},
  "registers": {"chat": {}, "analysis": {}, "task": {}, "emotional": {}, "crisis": {}},
  "quiet_hours": [],
  "signature_triggers": [],
  "persona_layers": [{"layer_id": "surface", "unlock_condition": null, "modifiers": {}}],
  "dynamic_state_rules": {},
  "milestone_conditions": {},
  "interim_lines": {},
  "bootstrap": {"style_instruction": "string", "opening_line": "string", "max_rounds": 3}
}""",
  (
    "Preserve the persona spine unless there is a direct contradiction that must be resolved.",
    "Remove contradictions, duplicated rules, legacy fields, and module-specific drift.",
    "Ensure all five required registers exist and task, analysis, and crisis stay useful before expressive.",
    "Ensure at least three signature triggers and two quiet-hour clamps are present; at least one trigger should be specific to the persona concept rather than a generic fallback.",
    "Keep surface exactly fixed and put relationship-depth behavior only in non-surface layers.",
    "Keep target-language prose consistent, with appearance_prompt in English.",
  ),
)


def normalize_generated_personality_payload(payload: Dict[str, Any], target_language: str = "English") -> Dict[str, Any]:
    """Normalize common scalar mismatches and complete required runtime fields."""
    payload = _clean_generated_text_tree(payload)
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
    _complete_bootstrap(payload, target_language=target_language)
    _complete_examples(payload)

    _complete_dynamic_state_rules(payload)
    payload["milestone_conditions"] = _string_dict(payload.get("milestone_conditions"))
    interim_lines = payload.get("interim_lines") if isinstance(payload.get("interim_lines"), dict) else {}
    payload["interim_lines"] = {str(key): _string_list(value) for key, value in interim_lines.items()}

    return payload


def _current_config_block(current_config: Optional[PersonalityConfigModel]) -> str:
  if current_config is None:
    return ""
  return "\n\n# Existing Draft Config\n" + json.dumps(
    current_config.model_dump(),
    ensure_ascii=False,
    indent=2,
  )


def _base_user_prompt(description: str, target_language: str, current_config: Optional[PersonalityConfigModel]) -> str:
  return f"""# User Context
Target Language: {target_language}

# User Input
{description}{_current_config_block(current_config)}

# Task
Extract the stable persona spine. Preserve explicit user-authored draft fields when they clearly conflict with generated guesses."""


def _module_user_prompt(
  description: str,
  target_language: str,
  spine: dict[str, Any],
  current_config: Optional[PersonalityConfigModel],
  task: str,
) -> str:
  return f"""# User Context
Target Language: {target_language}

# User Input
{description}{_current_config_block(current_config)}

# Persona Spine
{json.dumps(spine, ensure_ascii=False, indent=2)}

# Module Task
{task}"""


async def _run_generation_stage(
  *,
  stage_id: str,
  prompt: str,
  system_prompt: str,
  max_tokens: int,
  temperature: float,
  llm_override: Optional[LLMSettings],
  adapter_resolver: Callable[..., Any],
  adapter_factory: Callable[..., Any],
  stage_progress_callback: Optional[Callable[[str, str], None]] = None,
) -> dict[str, Any]:
  """Run one LLM JSON stage behind the shared generation concurrency gate."""
  async with _PERSONALITY_GENERATION_LLM_SEMAPHORE:
    if stage_progress_callback is not None:
      stage_progress_callback(stage_id, "running")
    llm_adapter = adapter_resolver(
      LLMScenario.CORE,
      llm_settings=llm_override,
      adapter_factory=adapter_factory,
    )
    logger.info(
      "[AI Generate Personality] Stage %s using provider=%s model=%s",
      stage_id,
      getattr(llm_adapter, "provider_name", "unknown"),
      getattr(llm_adapter, "model_name", "unknown"),
    )
    bridge = LLMProviderBridge(llm_adapter)
    response = await bridge.chat(
      system_prompt=system_prompt,
      messages=[{"role": "user", "content": prompt}],
      max_tokens=max_tokens,
      temperature=temperature,
      json_mode=True,
      disable_thinking=True,
      event_context={
        "request_kind": "personality:generation",
        "agent_id": "personality_generation",
      },
    )
  response_text = response.strip()
  logger.info(
    "[AI Generate Personality] Stage %s raw response preview: %s",
    stage_id,
    response_text[:300],
  )
  return _extract_json_object(response_text)


async def _run_optional_generation_stage(
  *,
  stages: list[dict[str, str]],
  allowed_keys: Sequence[str],
  **kwargs: Any,
) -> dict[str, Any]:
  stage_id = str(kwargs["stage_id"])
  try:
    data = await _run_generation_stage(**kwargs)
    progress_callback = kwargs.get("stage_progress_callback")
    if callable(progress_callback):
      progress_callback(stage_id, "completed")
    stages.append({"stage_id": stage_id, "status": "completed"})
    return _pick_keys(data, allowed_keys)
  except Exception as exc:  # noqa: BLE001 - optional sections can be normalized later
    logger.warning("[AI Generate Personality] Optional stage %s failed: %s", stage_id, exc)
    progress_callback = kwargs.get("stage_progress_callback")
    if callable(progress_callback):
      progress_callback(stage_id, "failed")
    stages.append({"stage_id": stage_id, "status": "failed"})
    return {}


def _stage_reports(status_by_id: dict[str, str]) -> list[dict[str, str]]:
  return [
    {
      "stage_id": item["stage_id"],
      "label": item["label"],
      "status": status_by_id.get(item["stage_id"], "completed"),
    }
    for item in GENERATION_STAGE_DEFINITIONS
  ]


def _initial_stage_reports() -> list[dict[str, str]]:
  return [
    {"stage_id": item["stage_id"], "label": item["label"], "status": "pending"}
    for item in GENERATION_STAGE_DEFINITIONS
  ]


def _set_stage_status(stages: list[dict[str, str]], stage_id: str, status: str) -> None:
  for item in stages:
    if item.get("stage_id") == stage_id:
      item["status"] = status
      return
  stages.append({"stage_id": stage_id, "label": stage_id, "status": status})


def _personality_generation_job_snapshot(job: PersonalityGenerationJob) -> dict[str, Any]:
  payload: dict[str, Any] = {
    "job_id": job.job_id,
    "status": job.status,
    "stages": [dict(item) for item in job.stages],
    "created_at": job.created_at,
    "updated_at": job.updated_at,
  }
  if job.result is not None:
    payload["data"] = job.result.config.model_dump()
    payload["stages"] = job.result.stages
  if job.error:
    payload["error"] = job.error
  return payload


def _cleanup_personality_generation_jobs(now: Optional[float] = None) -> None:
  current_time = now or time.time()
  ttl_seconds = PERSONALITY_GENERATION_JOB_TTL_SECONDS
  try:
    from ...config import get_config
    ttl_seconds = get_config().lifecycle.ephemeral_jobs.personality_generation_ttl_seconds
  except Exception:
    ttl_seconds = PERSONALITY_GENERATION_JOB_TTL_SECONDS
  expired_ids = [
    job_id
    for job_id, job in _PERSONALITY_GENERATION_JOBS.items()
    if current_time - job.updated_at > ttl_seconds
  ]
  for job_id in expired_ids:
    _PERSONALITY_GENERATION_JOBS.pop(job_id, None)


async def start_personality_generation_job(
  description: str,
  target_language: str = "English",
  current_config: Optional[PersonalityConfigModel] = None,
  llm_override: Optional[LLMSettings] = None,
  *,
  adapter_resolver: Callable[..., Any] = resolve_adapter_for_scenario,
  adapter_factory: Callable[..., Any] = create_llm_adapter,
) -> dict[str, Any]:
  """Start a background persona generation job and return its initial snapshot."""
  _cleanup_personality_generation_jobs()
  now = time.time()
  job = PersonalityGenerationJob(
    job_id=str(uuid.uuid4()),
    status="running",
    stages=_initial_stage_reports(),
    created_at=now,
    updated_at=now,
  )
  _PERSONALITY_GENERATION_JOBS[job.job_id] = job
  asyncio.create_task(_run_personality_generation_job(
    job,
    description=description,
    target_language=target_language,
    current_config=current_config,
    llm_override=llm_override,
    adapter_resolver=adapter_resolver,
    adapter_factory=adapter_factory,
  ))
  return _personality_generation_job_snapshot(job)


async def get_personality_generation_job(job_id: str) -> Optional[dict[str, Any]]:
  """Return a generation job snapshot if the in-memory job is still available."""
  _cleanup_personality_generation_jobs()
  job = _PERSONALITY_GENERATION_JOBS.get(job_id)
  if job is None:
    return None
  return _personality_generation_job_snapshot(job)


async def _run_personality_generation_job(
  job: PersonalityGenerationJob,
  *,
  description: str,
  target_language: str,
  current_config: Optional[PersonalityConfigModel],
  llm_override: Optional[LLMSettings],
  adapter_resolver: Callable[..., Any],
  adapter_factory: Callable[..., Any],
) -> None:
  def update_stage(stage_id: str, status: str) -> None:
    _set_stage_status(job.stages, stage_id, status)
    job.updated_at = time.time()

  try:
    result = await generate_personality_config_result(
      description,
      target_language=target_language,
      current_config=current_config,
      llm_override=llm_override,
      adapter_resolver=adapter_resolver,
      adapter_factory=adapter_factory,
      stage_progress_callback=update_stage,
    )
    job.result = result
    job.stages = result.stages
    job.status = "completed"
    job.updated_at = time.time()
  except Exception as exc:  # noqa: BLE001 - surfaced through job status endpoint
    job.error = str(exc)
    job.status = "failed"
    job.updated_at = time.time()


async def generate_personality_config_result(
  description: str,
  target_language: str = "English",
  current_config: Optional[PersonalityConfigModel] = None,
  llm_override: Optional[LLMSettings] = None,
  *,
  adapter_resolver: Callable[..., Any] = resolve_adapter_for_scenario,
  adapter_factory: Callable[..., Any] = create_llm_adapter,
  stage_progress_callback: Optional[Callable[[str, str], None]] = None,
) -> PersonalityGenerationResult:
  """Generate personality configuration through staged LLM calls."""
  stage_status: list[dict[str, str]] = []
  resolved_target_language = _resolve_generation_target_language(description, target_language, current_config)
  try:
    base_data = await _run_generation_stage(
      stage_id="base",
      prompt=_base_user_prompt(description, resolved_target_language, current_config),
      system_prompt=BASE_SPINE_SYSTEM_PROMPT,
      max_tokens=1100,
      temperature=0.65,
      llm_override=llm_override,
      adapter_resolver=adapter_resolver,
      adapter_factory=adapter_factory,
      stage_progress_callback=stage_progress_callback,
    )
    if stage_progress_callback is not None:
      stage_progress_callback("base", "completed")
    stage_status.append({"stage_id": "base", "status": "completed"})
    combined = _pick_keys(
      base_data,
      ("name", "avatar", "description", "identity_core", "idiolect"),
    )

    module_kwargs = {
      "llm_override": llm_override,
      "adapter_resolver": adapter_resolver,
      "adapter_factory": adapter_factory,
      "stage_progress_callback": stage_progress_callback,
    }
    module_tasks = [
      _run_optional_generation_stage(
        stages=stage_status,
        allowed_keys=("registers",),
        stage_id="registers",
        prompt=_module_user_prompt(
          description,
          resolved_target_language,
          combined,
          current_config,
          "Design all required registers with examples that match the spine.",
        ),
        system_prompt=REGISTER_SYSTEM_PROMPT,
        max_tokens=1500,
        temperature=0.7,
        **module_kwargs,
      ),
      _run_optional_generation_stage(
        stages=stage_status,
        allowed_keys=("quiet_hours", "signature_triggers", "dynamic_state_rules", "milestone_conditions"),
        stage_id="rules",
        prompt=_module_user_prompt(
          description,
          resolved_target_language,
          combined,
          current_config,
          "Design the persona's trigger signatures, quiet-hour clamps, and state convergence rules.",
        ),
        system_prompt=RULES_SYSTEM_PROMPT,
        max_tokens=1500,
        temperature=0.7,
        **module_kwargs,
      ),
      _run_optional_generation_stage(
        stages=stage_status,
        allowed_keys=("persona_layers",),
        stage_id="layers",
        prompt=_module_user_prompt(
          description,
          resolved_target_language,
          combined,
          current_config,
          "Design only the fixed surface baseline and non-surface deep persona layers.",
        ),
        system_prompt=LAYERS_SYSTEM_PROMPT,
        max_tokens=900,
        temperature=0.65,
        **module_kwargs,
      ),
      _run_optional_generation_stage(
        stages=stage_status,
        allowed_keys=("registers", "bootstrap", "interim_lines"),
        stage_id="bootstrap",
        prompt=_module_user_prompt(
          description,
          resolved_target_language,
          combined,
          current_config,
          "Write register examples, bootstrap first-contact copy, and sparse interim lines.",
        ),
        system_prompt=BOOTSTRAP_SYSTEM_PROMPT,
        max_tokens=1300,
        temperature=0.72,
        **module_kwargs,
      ),
      _run_optional_generation_stage(
        stages=stage_status,
        allowed_keys=("appearance_prompt",),
        stage_id="appearance",
        prompt=_module_user_prompt(
          description,
          resolved_target_language,
          combined,
          current_config,
          "Write the portrait prompt only.",
        ),
        system_prompt=APPEARANCE_SYSTEM_PROMPT,
        max_tokens=350,
        temperature=0.55,
        **module_kwargs,
      ),
    ]

    for fragment in await asyncio.gather(*module_tasks):
      _deep_merge_payload(combined, fragment)

    try:
      integrated = await _run_generation_stage(
        stage_id="integrate",
        prompt=f"""# User Context
Target Language: {resolved_target_language}

# User Input
{description}

# Combined Draft
{json.dumps(combined, ensure_ascii=False, indent=2)}

# Task
Resolve contradictions and return the final complete persona configuration JSON.""",
        system_prompt=INTEGRATION_SYSTEM_PROMPT,
        max_tokens=2600,
        temperature=0.45,
        llm_override=llm_override,
        adapter_resolver=adapter_resolver,
        adapter_factory=adapter_factory,
        stage_progress_callback=stage_progress_callback,
      )
      _deep_merge_payload(combined, integrated)
      if stage_progress_callback is not None:
        stage_progress_callback("integrate", "completed")
      stage_status.append({"stage_id": "integrate", "status": "completed"})
    except Exception as exc:  # noqa: BLE001 - normalization can still complete the combined draft
      logger.warning("[AI Generate Personality] Integration stage failed: %s", exc)
      if stage_progress_callback is not None:
        stage_progress_callback("integrate", "failed")
      stage_status.append({"stage_id": "integrate", "status": "failed"})

    data = normalize_generated_personality_payload(combined, target_language=resolved_target_language)
    if not data.get("name"):
      data["name"] = "AI Assistant"
    status_by_id = {item["stage_id"]: item["status"] for item in stage_status}
    return PersonalityGenerationResult(
      config=PersonalityConfigModel(**data),
      stages=_stage_reports(status_by_id),
    )
  except json.JSONDecodeError as exc:
    logger.error("[AI Generate Personality] JSON decode failed: %s", exc)
    raise ValueError(f"AI returned invalid JSON format: {exc}") from exc
  except Exception:
    logger.error("[AI Generate Personality] Generation failed")
    raise


async def generate_personality_config(
  description: str,
  target_language: str = "English",
  current_config: Optional[PersonalityConfigModel] = None,
  llm_override: Optional[LLMSettings] = None,
  *,
  adapter_resolver: Callable[..., Any] = resolve_adapter_for_scenario,
  adapter_factory: Callable[..., Any] = create_llm_adapter,
) -> PersonalityConfigModel:
  """Generate personality configuration from description using LLM."""
  result = await generate_personality_config_result(
    description,
    target_language=target_language,
    current_config=current_config,
    llm_override=llm_override,
    adapter_resolver=adapter_resolver,
    adapter_factory=adapter_factory,
  )
  return result.config


__all__ = [
    "GENERATION_STAGE_DEFINITIONS",
    "PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS",
    "PERSONALITY_GENERATION_JOB_TTL_SECONDS",
    "PERSONA_GENERATION_SHARED_DIRECTIVES",
    "PersonalityGenerationJob",
    "PersonalityGenerationResult",
    "REQUIRED_REGISTERS",
    "get_personality_generation_job",
    "generate_personality_config",
    "generate_personality_config_result",
    "normalize_generated_personality_payload",
    "start_personality_generation_job",
]