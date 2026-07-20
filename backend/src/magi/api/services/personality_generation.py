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
from ..routers.personality_config_schemas import (
  LayerModifiersModel,
  PersonaGenerationIntentModel,
  PersonalityConfigModel,
  SUPPORTED_LAYER_MODIFIER_KEYS,
)
from .personality_generation_prompts import (
    APPEARANCE_SYSTEM_PROMPT,
    BASE_SPINE_SYSTEM_PROMPT,
    BOOTSTRAP_SYSTEM_PROMPT,
    INTEGRATION_SYSTEM_PROMPT,
    LAYERS_SYSTEM_PROMPT,
    PERSONA_GENERATION_SHARED_DIRECTIVES,
    REGISTER_SYSTEM_PROMPT,
    RULES_SYSTEM_PROMPT,
)

logger = get_logger(__name__)


REQUIRED_REGISTERS = ("chat", "analysis", "task", "emotional", "crisis")
# Upper bound on persona-generation LLM calls launched at once. The parallel
# module phase fans out five stages (registers, rules, layers, bootstrap,
# appearance); this cap must cover them so it does not become the bottleneck.
# Actual provider/model load is still governed downstream by the per-model
# LLMConcurrencyLimiter (which is model-aware and reserves high-priority slots).
PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS = 6
PERSONALITY_GENERATION_JOB_TTL_SECONDS = 30 * 60
_PERSONALITY_GENERATION_LLM_SEMAPHORE = asyncio.Semaphore(PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS)
_PERSONALITY_GENERATION_JOBS: dict[str, "PersonalityGenerationJob"] = {}
_PERSONALITY_GENERATION_REQUEST_INDEX: dict[str, str] = {}
JSON_DIAGNOSTIC_CONTRACT_CHARS = 2400
JSON_DIAGNOSTIC_OUTPUT_CHARS = 1600
JSON_DIAGNOSTIC_LINE_CONTEXT = 2
META_DESIGN_KEY = "_meta_design"
META_DESIGN_FIELDS = ("core_theme", "failure_mode", "key_constraint")
GENERATION_INTERNAL_KEYS = frozenset({META_DESIGN_KEY})
FIXED_SURFACE_LAYER = {"layer_id": "surface", "unlock_condition": None, "modifiers": {}}
CJK_TEXT_RE = re.compile(r"[\u3400-\u9fff]")
CJK_INTERNAL_SPACE_RE = re.compile(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])")
CJK_BEFORE_PUNCTUATION_RE = re.compile(r"(?<=[\u3400-\u9fff])\s+(?=[，。！？、；：])")
ENGLISH_BOOTSTRAP_PREFIXES = ("hi, i'm ", "hello, i'm ", "hi, i am ", "hello, i am ")
AMBIGUOUS_LANGUAGE_VALUES = {"", "auto", "automatic", "自动"}
REGISTER_ALIASES = {
  "ordinary": "chat",
  "ordinary_conversation": "chat",
  "casual": "chat",
  "daily": "chat",
  "daily_conversation": "chat",
  "conversation": "chat",
  "work": "task",
  "execution": "task",
  "task_execution": "task",
  "tool_use": "task",
  "planning": "analysis",
  "deep_analysis": "analysis",
  "support": "emotional",
  "emotional_support": "emotional",
  "care": "emotional",
  "safety": "crisis",
  "urgent": "crisis",
  "emergency": "crisis",
}
JSON_REPAIR_SYSTEM_PROMPT = """You repair invalid JSON from a persona-generation stage.
Output ONLY one valid JSON object. Do not add markdown fences, comments, or explanation.
Preserve the original keys and values as much as possible. Only fix syntax and obvious JSON-shape mistakes needed for parsing."""
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
  draft_id: Optional[str] = None
  request_id: Optional[str] = None
  result: Optional[PersonalityGenerationResult] = None
  error: Optional[str] = None


@dataclass(frozen=True)
class _GenerationRunContext:
  description: str
  target_language: str
  current_config: Optional[PersonalityConfigModel]
  llm_override: Optional[LLMSettings]
  intent: Optional[PersonaGenerationIntentModel]
  adapter_resolver: Callable[..., Any]
  adapter_factory: Callable[..., Any]
  stage_progress_callback: Optional[Callable[[str, str], None]]


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


def _string_field(value: Any, fallback: str = "") -> str:
  if value is None:
    return fallback
  if isinstance(value, str):
    return value.strip() or fallback
  if isinstance(value, list):
    items = [str(item).strip() for item in value if str(item).strip()]
    return "\n".join(items) or fallback
  if isinstance(value, dict):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
  return str(value).strip() or fallback


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


def _json_candidate_text(response_text: str) -> str:
  """Return the response slice that is parsed as JSON."""
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
  return text


def _extract_json_object(response_text: str) -> dict[str, Any]:
  """Parse the first JSON object from an LLM response."""
  text = _json_candidate_text(response_text)
  data = json.loads(text)
  if not isinstance(data, dict):
    raise ValueError("AI returned JSON that is not an object")
  return data


def _truncate_for_diagnostics(value: str, max_chars: int) -> str:
  if len(value) <= max_chars:
    return value
  half = max_chars // 2
  return f"{value[:half]}\n...[truncated {len(value) - max_chars} chars]...\n{value[-half:]}"


def _expected_output_contract(system_prompt: str) -> str:
  marker = "# Output Contract"
  end_marker = "# Stage Quality Checks"
  start = system_prompt.find(marker)
  if start < 0:
    return _truncate_for_diagnostics(system_prompt.strip(), JSON_DIAGNOSTIC_CONTRACT_CHARS)
  start += len(marker)
  end = system_prompt.find(end_marker, start)
  contract = system_prompt[start:end if end >= 0 else len(system_prompt)].strip()
  return _truncate_for_diagnostics(contract, JSON_DIAGNOSTIC_CONTRACT_CHARS)


def _parse_error_summary(exc: Exception) -> dict[str, Any]:
  if isinstance(exc, json.JSONDecodeError):
    return {
      "type": exc.__class__.__name__,
      "message": exc.msg,
      "line": exc.lineno,
      "column": exc.colno,
      "char": exc.pos,
    }
  return {
    "type": exc.__class__.__name__,
    "message": str(exc),
  }


def _line_excerpt_with_caret(line: str, column: int, *, radius: int = 180) -> tuple[str, str]:
  index = max(column - 1, 0)
  start = max(index - radius, 0)
  end = min(index + radius, len(line))
  prefix = "..." if start > 0 else ""
  suffix = "..." if end < len(line) else ""
  excerpt = f"{prefix}{line[start:end]}{suffix}"
  caret_index = len(prefix) + max(index - start, 0)
  return excerpt, " " * caret_index + "^"


def _json_output_error_context(response_text: str, exc: Exception) -> str:
  try:
    candidate = _json_candidate_text(response_text)
  except Exception:
    candidate = response_text.strip()
  if not isinstance(exc, json.JSONDecodeError):
    return _truncate_for_diagnostics(candidate, JSON_DIAGNOSTIC_OUTPUT_CHARS)

  lines = candidate.splitlines() or [candidate]
  line_index = max(min(exc.lineno - 1, len(lines) - 1), 0)
  start = max(line_index - JSON_DIAGNOSTIC_LINE_CONTEXT, 0)
  end = min(line_index + JSON_DIAGNOSTIC_LINE_CONTEXT + 1, len(lines))
  rendered: list[str] = []
  for current in range(start, end):
    line_no = current + 1
    marker = ">" if current == line_index else " "
    if current == line_index:
      excerpt, caret = _line_excerpt_with_caret(lines[current], exc.colno)
      rendered.append(f"{marker} {line_no}: {excerpt}")
      rendered.append(f"  {' ' * (len(str(line_no)) + 2)}{caret}")
    else:
      rendered.append(f"{marker} {line_no}: {_truncate_for_diagnostics(lines[current], 420)}")
  return "\n".join(rendered)


def _json_output_preview(response_text: str) -> str:
  try:
    candidate = _json_candidate_text(response_text)
  except Exception:
    candidate = response_text.strip()
  return _truncate_for_diagnostics(candidate, JSON_DIAGNOSTIC_OUTPUT_CHARS)


def _log_invalid_generation_json(
  *,
  event: str,
  stage_id: str,
  system_prompt: str,
  response_text: str,
  parse_error: Exception,
  extra_fields: Optional[dict[str, Any]] = None,
) -> None:
  fields: dict[str, Any] = {
    "stage_id": stage_id,
    "expected_output_contract": _expected_output_contract(system_prompt),
    "parse_error": _parse_error_summary(parse_error),
    "output_error_context": _json_output_error_context(response_text, parse_error),
    "output_preview": _json_output_preview(response_text),
  }
  if extra_fields:
    fields.update(extra_fields)
  logger.warning(event, **fields)


def _json_repair_user_prompt(stage_id: str, response_text: str, error: Exception) -> str:
  return f"""Repair this invalid JSON from the {stage_id} persona-generation stage.

Parse error:
{error}

Return only the repaired JSON object. Do not summarize or change the content.

# Invalid JSON
{response_text}"""


async def _call_generation_llm(
  *,
  stage_id: str,
  prompt: str,
  system_prompt: str,
  max_tokens: int,
  temperature: float,
  llm_override: Optional[LLMSettings],
  adapter_resolver: Callable[..., Any],
  adapter_factory: Callable[..., Any],
  stage_progress_callback: Optional[Callable[[str, str], None]],
  notify_progress: bool = True,
) -> str:
  async with _PERSONALITY_GENERATION_LLM_SEMAPHORE:
    if notify_progress and stage_progress_callback is not None:
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
  return response.strip()


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


def _generation_meta_design(spine: dict[str, Any]) -> dict[str, str]:
  raw_meta = spine.get(META_DESIGN_KEY) if isinstance(spine, dict) else None
  meta = raw_meta if isinstance(raw_meta, dict) else {}
  return {
    "core_theme": str(meta.get("core_theme") or "[not specified - infer from the persona spine]"),
    "failure_mode": str(meta.get("failure_mode") or "[not specified - apply general anti-AI-performance principles]"),
    "key_constraint": str(meta.get("key_constraint") or "[not specified - keep ordinary presence stronger than style markers]"),
  }


def _complete_generation_meta_design(payload: dict[str, Any]) -> None:
  raw_meta = payload.get(META_DESIGN_KEY)
  meta = raw_meta if isinstance(raw_meta, dict) else {}
  payload[META_DESIGN_KEY] = {
    field: str(meta.get(field) or "")
    for field in META_DESIGN_FIELDS
  }


def _runtime_payload_from_combined(payload: dict[str, Any]) -> dict[str, Any]:
  """Drop generation-only design anchors before runtime schema validation."""
  return {
    key: value
    for key, value in payload.items()
    if key not in GENERATION_INTERNAL_KEYS
  }


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


def _normalize_register_id(value: Any, default_register: str = "chat") -> str:
  normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
  if normalized in REQUIRED_REGISTERS:
    return normalized
  return REGISTER_ALIASES.get(normalized, default_register)


def _stringify_runtime_example(value: Any) -> str:
  if isinstance(value, str):
    return value.strip()
  if not isinstance(value, dict):
    return _string_field(value)

  user_text = _string_field(
    value.get("user_input")
    or value.get("user")
    or value.get("input")
    or value.get("prompt")
  )
  assistant_text = _string_field(
    value.get("assistant_output")
    or value.get("assistant")
    or value.get("response")
    or value.get("good_response")
    or value.get("output")
  )
  if assistant_text:
    return f"[User: {user_text}]\nGood: {assistant_text}" if user_text else f"Good: {assistant_text}"
  return _string_field(value.get("text") or value.get("example"))


def _collect_register_examples(value: Any, default_register: str) -> list[tuple[str, str]]:
  collected: list[tuple[str, str]] = []
  if isinstance(value, list):
    for item in value:
      collected.extend(_collect_register_examples(item, default_register))
    return collected

  if isinstance(value, dict):
    register = _normalize_register_id(
      value.get("register")
      or value.get("register_id")
      or value.get("mode")
      or value.get("category"),
      default_register,
    )
    if "examples" in value:
      collected.extend(_collect_register_examples(value.get("examples"), register))
      return collected
    example = _stringify_runtime_example(value)
    if example:
      collected.append((register, example))
    return collected

  example = _stringify_runtime_example(value)
  if example:
    collected.append((default_register, example))
  return collected


def _append_register_examples(registers: dict[str, Any], value: Any, default_register: str) -> None:
  for register, example in _collect_register_examples(value, default_register):
    item = registers.get(register)
    if not isinstance(item, dict):
      item = {}
      registers[register] = item
    examples = _string_list(item.get("examples"))
    if example not in examples:
      examples.append(example)
    item["examples"] = examples


def _complete_registers(payload: Dict[str, Any]) -> None:
  registers = _ensure_dict(payload, "registers")
  _append_register_examples(registers, registers.pop("examples", None), "chat")
  for register, item in list(registers.items()):
    if not isinstance(item, dict):
      registers.pop(register, None)
  for register in REQUIRED_REGISTERS:
    item = registers.get(register)
    if not isinstance(item, dict):
      item = {}
      registers[register] = item
    defaults = _default_register(register)
    raw_examples = item.get("examples")
    item["description"] = _string_field(item.get("description"), defaults["description"])
    item["behavior"] = _string_field(item.get("behavior"), defaults["behavior"])
    item["examples"] = []
    _append_register_examples(registers, raw_examples, register)


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
    raw_chattiness = idiolect.get("chattiness")
    if raw_chattiness is None:
        idiolect["chattiness"] = 0.5
    else:
        try:
            idiolect["chattiness"] = max(0.0, min(1.0, float(raw_chattiness)))
        except (TypeError, ValueError):
            idiolect["chattiness"] = 0.5

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


def _generation_intent_block(intent: Optional[PersonaGenerationIntentModel]) -> str:
  if intent is None:
    return """# Resolved Generation Intent
No user-confirmed reference resolution was provided. Infer conservatively from the description, do not claim reference fidelity, and do not invent unsupported identity facts."""
  return "# Resolved Generation Intent\n" + json.dumps(
    intent.model_dump(),
    ensure_ascii=False,
    indent=2,
  )


def _base_user_prompt(
  description: str,
  target_language: str,
  current_config: Optional[PersonalityConfigModel],
  intent: Optional[PersonaGenerationIntentModel] = None,
) -> str:
  return f"""# User Context
Target Language: {target_language}

# User Input
{description}{_current_config_block(current_config)}

{_generation_intent_block(intent)}

# Task
Extract the stable persona spine. Preserve explicit user-authored draft fields when they clearly conflict with generated guesses."""


def _module_user_prompt(
  description: str,
  target_language: str,
  spine: dict[str, Any],
  current_config: Optional[PersonalityConfigModel],
  task: str,
  intent: Optional[PersonaGenerationIntentModel] = None,
) -> str:
  meta_design = _generation_meta_design(spine)
  return f"""# User Context
Target Language: {target_language}

# User Input
{description}{_current_config_block(current_config)}

{_generation_intent_block(intent)}

# Persona Spine
{json.dumps(spine, ensure_ascii=False, indent=2)}

# Design Anchors
The persona's design intent is captured in _meta_design within the spine. All outputs from this stage MUST serve these anchors:

- core_theme: {meta_design["core_theme"]}
- failure_mode_to_avoid: {meta_design["failure_mode"]}
- key_constraint: {meta_design["key_constraint"]}

If your output drifts toward the failure_mode_to_avoid, revise before returning.

# Module Task
{task}"""


def _integration_user_prompt(
  description: str,
  target_language: str,
  combined: dict[str, Any],
  intent: Optional[PersonaGenerationIntentModel] = None,
) -> str:
  return f"""# User Context
Target Language: {target_language}

# User Input
{description}

{_generation_intent_block(intent)}

# Combined Draft
{json.dumps(combined, ensure_ascii=False, indent=2)}

# Task
Conduct the cross-field consistency review from the system prompt. Identify the fields that contradict each other or fail to support the persona's _meta_design, and return ONLY those corrected fields. Omit anything already coherent, and return an empty object {{}} if nothing needs changing. Follow the output contract in the system prompt: mirror the draft's key paths, and for any array you change return the complete corrected array.

Pay particular attention to:
- Whether chat register examples resist the declared failure mode without including bad examples in the final runtime examples
- Whether vocab and sentence_style declarations match what examples actually demonstrate
- Whether crisis register meets safety-first requirements without inventing region-specific resources
- Whether relationship layers feel like the same character at different depths

Return only the JSON patch, no commentary, and do not include _meta_design."""


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
  retry_on_json_error: bool = False,
) -> dict[str, Any]:
  """Run one LLM JSON stage behind the shared generation concurrency gate."""
  response_text = await _call_generation_llm(
    stage_id=stage_id,
    prompt=prompt,
    system_prompt=system_prompt,
    max_tokens=max_tokens,
    temperature=temperature,
    llm_override=llm_override,
    adapter_resolver=adapter_resolver,
    adapter_factory=adapter_factory,
    stage_progress_callback=stage_progress_callback,
  )
  logger.info(
    "[AI Generate Personality] Stage %s raw response preview: %s",
    stage_id,
    response_text[:300],
  )
  try:
    return _extract_json_object(response_text)
  except (json.JSONDecodeError, ValueError) as exc:
    if not retry_on_json_error:
      raise
    _log_invalid_generation_json(
      event="personality_generation_invalid_json",
      stage_id=stage_id,
      system_prompt=system_prompt,
      response_text=response_text,
      parse_error=exc,
      extra_fields={"will_retry_repair": True},
    )
    repaired_text = await _call_generation_llm(
      stage_id=f"{stage_id}.repair",
      prompt=_json_repair_user_prompt(stage_id, response_text, exc),
      system_prompt=JSON_REPAIR_SYSTEM_PROMPT,
      max_tokens=max_tokens,
      temperature=0.0,
      llm_override=llm_override,
      adapter_resolver=adapter_resolver,
      adapter_factory=adapter_factory,
      stage_progress_callback=stage_progress_callback,
      notify_progress=False,
    )
    logger.info(
      "[AI Generate Personality] Stage %s repaired response preview: %s",
      stage_id,
      repaired_text[:300],
    )
    try:
      return _extract_json_object(repaired_text)
    except (json.JSONDecodeError, ValueError) as repair_exc:
      _log_invalid_generation_json(
        event="personality_generation_json_repair_invalid",
        stage_id=stage_id,
        system_prompt=system_prompt,
        response_text=repaired_text,
        parse_error=repair_exc,
        extra_fields={
          "original_parse_error": _parse_error_summary(exc),
          "repair_parse_error": _parse_error_summary(repair_exc),
          "repair_output_error_context": _json_output_error_context(repaired_text, repair_exc),
        },
      )
      raise


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
  if job.draft_id:
    payload["draft_id"] = job.draft_id
  if job.request_id:
    payload["request_id"] = job.request_id
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
  if expired_ids:
    expired_set = set(expired_ids)
    for request_id, job_id in list(_PERSONALITY_GENERATION_REQUEST_INDEX.items()):
      if job_id in expired_set:
        _PERSONALITY_GENERATION_REQUEST_INDEX.pop(request_id, None)


async def start_personality_generation_job(
  description: str,
  target_language: str = "English",
  current_config: Optional[PersonalityConfigModel] = None,
  llm_override: Optional[LLMSettings] = None,
  draft_id: Optional[str] = None,
  request_id: Optional[str] = None,
  intent: Optional[PersonaGenerationIntentModel] = None,
  *,
  adapter_resolver: Callable[..., Any] = resolve_adapter_for_scenario,
  adapter_factory: Callable[..., Any] = create_llm_adapter,
) -> dict[str, Any]:
  """Start a background persona generation job and return its initial snapshot."""
  _cleanup_personality_generation_jobs()
  if request_id:
    existing_job_id = _PERSONALITY_GENERATION_REQUEST_INDEX.get(request_id)
    existing_job = _PERSONALITY_GENERATION_JOBS.get(existing_job_id or "")
    if existing_job is not None:
      return _personality_generation_job_snapshot(existing_job)
  now = time.time()
  job = PersonalityGenerationJob(
    job_id=str(uuid.uuid4()),
    status="running",
    stages=_initial_stage_reports(),
    created_at=now,
    updated_at=now,
    draft_id=draft_id,
    request_id=request_id,
  )
  _PERSONALITY_GENERATION_JOBS[job.job_id] = job
  if request_id:
    _PERSONALITY_GENERATION_REQUEST_INDEX[request_id] = job.job_id
  asyncio.create_task(_run_personality_generation_job(
    job,
    description=description,
    target_language=target_language,
    current_config=current_config,
    llm_override=llm_override,
    intent=intent,
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
  intent: Optional[PersonaGenerationIntentModel],
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
      intent=intent,
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
  intent: Optional[PersonaGenerationIntentModel] = None,
  *,
  adapter_resolver: Callable[..., Any] = resolve_adapter_for_scenario,
  adapter_factory: Callable[..., Any] = create_llm_adapter,
  stage_progress_callback: Optional[Callable[[str, str], None]] = None,
) -> PersonalityGenerationResult:
  """Generate personality configuration through staged LLM calls."""
  stage_status: list[dict[str, str]] = []
  resolved_target_language = _resolve_generation_target_language(description, target_language, current_config)
  context = _GenerationRunContext(
    description=description,
    target_language=resolved_target_language,
    current_config=current_config,
    llm_override=llm_override,
    intent=intent,
    adapter_resolver=adapter_resolver,
    adapter_factory=adapter_factory,
    stage_progress_callback=stage_progress_callback,
  )
  try:
    combined = await _run_base_personality_stage(context, stage_status)
    await _run_module_personality_stages(context, stage_status, combined)
    await _run_integration_personality_stage(context, stage_status, combined)
    return _build_personality_generation_result(
      combined,
      stage_status,
      target_language=context.target_language,
    )
  except json.JSONDecodeError as exc:
    logger.error("[AI Generate Personality] JSON decode failed: %s", exc)
    raise ValueError(f"AI returned invalid JSON format: {exc}") from exc
  except Exception:
    logger.error("[AI Generate Personality] Generation failed")
    raise


async def _run_base_personality_stage(
  context: _GenerationRunContext,
  stage_status: list[dict[str, str]],
) -> dict[str, Any]:
  base_data = await _run_generation_stage(
    stage_id="base",
    prompt=_base_user_prompt(
      context.description,
      context.target_language,
      context.current_config,
      context.intent,
    ),
    system_prompt=BASE_SPINE_SYSTEM_PROMPT,
    max_tokens=1600,
    temperature=0.55,
    **_generation_stage_dependencies(context),
  )
  _record_completed_generation_stage(stage_status, context, "base")
  combined = _pick_keys(
    base_data,
    ("name", "avatar", "description", META_DESIGN_KEY, "identity_core", "idiolect"),
  )
  _complete_generation_meta_design(combined)
  return combined


async def _run_module_personality_stages(
  context: _GenerationRunContext,
  stage_status: list[dict[str, str]],
  combined: dict[str, Any],
) -> None:
  module_tasks = [
    _module_stage_task(
      context,
      stage_status,
      combined,
      allowed_keys=("registers",),
      stage_id="registers",
      system_prompt=REGISTER_SYSTEM_PROMPT,
      max_tokens=2000,
      temperature=0.7,
      task_prompt="Design all required registers with good-only runtime examples that match the spine and respect the persona's design anchors.",
    ),
    _module_stage_task(
      context,
      stage_status,
      combined,
      allowed_keys=("quiet_hours", "signature_triggers", "dynamic_state_rules", "milestone_conditions"),
      stage_id="rules",
      system_prompt=RULES_SYSTEM_PROMPT,
      max_tokens=1500,
      temperature=0.7,
      task_prompt="Design the persona's trigger signatures, quiet-hour clamps, and state convergence rules using _meta_design as the source of persona-specific trigger ideas.",
    ),
    _module_stage_task(
      context,
      stage_status,
      combined,
      allowed_keys=("persona_layers",),
      stage_id="layers",
      system_prompt=LAYERS_SYSTEM_PROMPT,
      max_tokens=1300,
      temperature=0.7,
      task_prompt="Design only the fixed surface baseline and non-surface deep persona layers as concrete diffs from the same _meta_design core theme.",
    ),
    _module_stage_task(
      context,
      stage_status,
      combined,
      allowed_keys=("registers", "bootstrap", "interim_lines"),
      stage_id="bootstrap",
      system_prompt=BOOTSTRAP_SYSTEM_PROMPT,
      max_tokens=1800,
      temperature=0.72,
      task_prompt="Write good-only register examples, bootstrap first-contact copy that fits _meta_design, and sparse interim lines.",
    ),
    _module_stage_task(
      context,
      stage_status,
      combined,
      allowed_keys=("appearance_prompt",),
      stage_id="appearance",
      system_prompt=APPEARANCE_SYSTEM_PROMPT,
      max_tokens=350,
      temperature=0.55,
      task_prompt="Write the portrait prompt only.",
    ),
  ]
  for fragment in await asyncio.gather(*module_tasks):
    _deep_merge_payload(combined, fragment)


def _module_stage_task(
  context: _GenerationRunContext,
  stage_status: list[dict[str, str]],
  combined: dict[str, Any],
  *,
  allowed_keys: Sequence[str],
  stage_id: str,
  system_prompt: str,
  max_tokens: int,
  temperature: float,
  task_prompt: str,
):
  return _run_optional_generation_stage(
    stages=stage_status,
    allowed_keys=allowed_keys,
    stage_id=stage_id,
    prompt=_module_user_prompt(
      context.description,
      context.target_language,
      combined,
      context.current_config,
      task_prompt,
      context.intent,
    ),
    system_prompt=system_prompt,
    max_tokens=max_tokens,
    temperature=temperature,
    **_generation_stage_dependencies(context),
  )


async def _run_integration_personality_stage(
  context: _GenerationRunContext,
  stage_status: list[dict[str, str]],
  combined: dict[str, Any],
) -> None:
  try:
    integrated = await _run_generation_stage(
      stage_id="integrate",
      prompt=_integration_user_prompt(
        context.description,
        context.target_language,
        combined,
        context.intent,
      ),
      system_prompt=INTEGRATION_SYSTEM_PROMPT,
      max_tokens=2048,
      temperature=0.4,
      retry_on_json_error=True,
      **_generation_stage_dependencies(context),
    )
    _deep_merge_payload(combined, integrated)
    _record_completed_generation_stage(stage_status, context, "integrate")
  except Exception as exc:  # noqa: BLE001 - normalization can still complete the combined draft
    logger.warning("[AI Generate Personality] Integration stage failed: %s", exc)
    if context.stage_progress_callback is not None:
      context.stage_progress_callback("integrate", "failed")
    stage_status.append({"stage_id": "integrate", "status": "failed"})


def _record_completed_generation_stage(
  stage_status: list[dict[str, str]],
  context: _GenerationRunContext,
  stage_id: str,
) -> None:
  if context.stage_progress_callback is not None:
    context.stage_progress_callback(stage_id, "completed")
  stage_status.append({"stage_id": stage_id, "status": "completed"})


def _generation_stage_dependencies(context: _GenerationRunContext) -> dict[str, Any]:
  return {
    "llm_override": context.llm_override,
    "adapter_resolver": context.adapter_resolver,
    "adapter_factory": context.adapter_factory,
    "stage_progress_callback": context.stage_progress_callback,
  }


def _build_personality_generation_result(
  combined: dict[str, Any],
  stage_status: list[dict[str, str]],
  *,
  target_language: str,
) -> PersonalityGenerationResult:
  data = normalize_generated_personality_payload(
    _runtime_payload_from_combined(combined),
    target_language=target_language,
  )
  if not data.get("name"):
    data["name"] = "AI Assistant"
  status_by_id = {item["stage_id"]: item["status"] for item in stage_status}
  return PersonalityGenerationResult(
    config=PersonalityConfigModel(**data),
    stages=_stage_reports(status_by_id),
  )


async def generate_personality_config(
  description: str,
  target_language: str = "English",
  current_config: Optional[PersonalityConfigModel] = None,
  llm_override: Optional[LLMSettings] = None,
  intent: Optional[PersonaGenerationIntentModel] = None,
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
    intent=intent,
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
