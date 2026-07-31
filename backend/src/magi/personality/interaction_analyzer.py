"""Lightweight LLM-based interaction quality analyzer."""

from __future__ import annotations

import json
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..utils.diagnostic_logging import full_content_logging_enabled
from ..config.models import LLMScenario
from ..core.logger import get_logger
from ..llm.provider import get_scenario_llm_pool
from ..llm.provider_bridge import LLMProviderBridge
from ..llm.provider_bridge.models import ProviderResponse
from .behavior_evolution import SatisfactionLevel
from .emotional_state import EngagementLevel, InteractionOutcome

logger = get_logger(__name__)

_SYSTEM_PROMPT = """\
You are an interaction quality classifier. Analyze a user–assistant exchange and output a JSON object with these fields:

- "sentiment": float from -1.0 (very negative) to 1.0 (very positive), reflecting the user's emotional tone.
- "engagement": one of "none", "low", "medium", "high", "very_high" — how actively the user is participating.
- "complexity": float from 0.0 (trivial small talk) to 1.0 (highly complex reasoning/task).
- "outcome": one of "success", "partial", "failure" — whether the assistant addressed the user's need.
- "satisfaction": one of "very_low", "low", "neutral", "high", "very_high" — estimated user satisfaction.

Output ONLY a JSON object. No explanations."""

_TOOL_SYSTEM_PROMPT = """\
You are a post-turn interaction observer. Analyze the user-assistant exchange after the assistant has already replied.

Always call submit_interaction_analysis exactly once with the interaction score.
Optionally call at most three memory observation tools when the user's own words provide explicit, durable evidence.

Rules:
- If there is no durable update, call only submit_interaction_analysis.
- Memory observations must be grounded in the user's message, not the assistant response.
- Do not infer long-term preferences from casual one-off wording.
- Do not write summaries or explanations in assistant text.
- Use remember_profile_signal for durable user profile or communication preferences.
- Use remember_task_preference for how the user wants future tasks handled.
- Use record_persona_relationship_signal for persona-specific trust, boundary, or milestone signals."""

_ENGAGEMENT_MAP = {
    "none": EngagementLevel.NONE,
    "low": EngagementLevel.LOW,
    "medium": EngagementLevel.MEDIUM,
    "high": EngagementLevel.HIGH,
    "very_high": EngagementLevel.VERY_HIGH,
}

_OUTCOME_MAP = {
    "success": InteractionOutcome.SUCCESS,
    "partial": InteractionOutcome.PARTIAL_SUCCESS,
    "failure": InteractionOutcome.FAILURE,
}

_OUTCOME_STRING_MAP = {
    InteractionOutcome.SUCCESS: "success",
    InteractionOutcome.PARTIAL_SUCCESS: "partial",
    InteractionOutcome.FAILURE: "failure",
}

_SATISFACTION_MAP = {
    "very_low": SatisfactionLevel.VERY_LOW,
    "low": SatisfactionLevel.LOW,
    "neutral": SatisfactionLevel.NEUTRAL,
    "high": SatisfactionLevel.HIGH,
    "very_high": SatisfactionLevel.VERY_HIGH,
}

_ANALYSIS_TOOL_NAME = "submit_interaction_analysis"
_PROFILE_SIGNAL_TOOL_NAME = "remember_profile_signal"
_TASK_PREFERENCE_TOOL_NAME = "remember_task_preference"
_RELATIONSHIP_SIGNAL_TOOL_NAME = "record_persona_relationship_signal"
_OBSERVATION_TOOL_KINDS = {
    _PROFILE_SIGNAL_TOOL_NAME: "profile_signal",
    _TASK_PREFERENCE_TOOL_NAME: "task_preference",
    _RELATIONSHIP_SIGNAL_TOOL_NAME: "persona_relationship_signal",
}


@dataclass(frozen=True, slots=True)
class InteractionObservation:
    """Structured post-turn observation emitted by the interaction analyzer."""

    kind: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InteractionAnalysis:
    """Result of analyzing a single user–assistant interaction turn."""

    sentiment: float
    engagement: EngagementLevel
    complexity: float
    outcome: InteractionOutcome
    satisfaction: SatisfactionLevel
    trigger_type: Optional[str] = None
    milestone_keys: List[str] = field(default_factory=list)
    memory_observations: List[InteractionObservation] = field(default_factory=list)

    @property
    def outcome_str(self) -> str:
        return _OUTCOME_STRING_MAP.get(self.outcome, "success")


DEFAULT_ANALYSIS = InteractionAnalysis(
    sentiment=0.0,
    engagement=EngagementLevel.MEDIUM,
    complexity=0.5,
    outcome=InteractionOutcome.SUCCESS,
    satisfaction=SatisfactionLevel.NEUTRAL,
)


def _build_system_prompt(
    stp_rules: List[Dict[str, str]] | None = None,
    milestone_conditions: Dict[str, str] | None = None,
) -> str:
    """Build the system prompt, optionally including STP trigger and milestone detection."""
    extra = ""

    # STP trigger detection block
    if stp_rules:
        rules_lines: list[str] = []
        trigger_types: list[str] = []
        for rule in stp_rules:
            tt = rule.get("trigger_type", "")
            cond = rule.get("trigger_condition", "")
            if tt and cond:
                rules_lines.append(f'- "{tt}": {cond}')
                trigger_types.append(f'"{tt}"')
        if rules_lines:
            extra += (
                "\n\nAdditionally, determine if the user's message activates any of "
                "these behavioral triggers:\n"
                + "\n".join(rules_lines)
                + "\n\nAdd this field to your JSON output:\n"
                '- "trigger_type": one of '
                + ", ".join(trigger_types)
                + " if a trigger condition is clearly matched, or null if none applies. "
                "Only activate a trigger when the conversation clearly matches the described condition."
            )

    # Milestone detection block
    if milestone_conditions:
        ms_lines: list[str] = []
        ms_keys: list[str] = []
        for key, cond in milestone_conditions.items():
            ms_lines.append(f'- "{key}": {cond}')
            ms_keys.append(f'"{key}"')
        if ms_lines:
            extra += (
                "\n\nAlso, determine if this exchange represents a significant "
                "relationship milestone. The following milestones may occur:\n"
                + "\n".join(ms_lines)
                + "\n\nAdd this field to your JSON output:\n"
                '- "milestone_keys": an array of milestone keys ('
                + ", ".join(ms_keys)
                + ") that are clearly achieved in this exchange, or an empty array if none. "
                "Only mark a milestone when the exchange unmistakably demonstrates "
                "the described condition — do not mark it for vague similarity."
            )

    if not extra:
        return _SYSTEM_PROMPT
    return _SYSTEM_PROMPT + extra


def _build_tool_system_prompt(
    stp_rules: List[Dict[str, str]] | None = None,
    milestone_conditions: Dict[str, str] | None = None,
) -> str:
    extra = ""
    legacy_prompt = _build_system_prompt(stp_rules, milestone_conditions)
    if legacy_prompt != _SYSTEM_PROMPT:
        extra = "\n\nAdditional scoring guidance:\n" + legacy_prompt
    return _TOOL_SYSTEM_PROMPT + extra


def _observer_tools() -> list[dict[str, Any]]:
    return [
        _analysis_tool(),
        _profile_signal_tool(),
        _task_preference_tool(),
        _relationship_signal_tool(),
    ]


def _function_tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def _analysis_tool() -> dict[str, Any]:
    return _function_tool(
        _ANALYSIS_TOOL_NAME,
        "Submit the required post-turn interaction score.",
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "sentiment": {"type": "number", "minimum": -1.0, "maximum": 1.0},
                "engagement": {
                    "type": "string",
                    "enum": ["none", "low", "medium", "high", "very_high"],
                },
                "complexity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "outcome": {"type": "string", "enum": ["success", "partial", "failure"]},
                "satisfaction": {
                    "type": "string",
                    "enum": ["very_low", "low", "neutral", "high", "very_high"],
                },
                "trigger_type": {"type": "string"},
                "milestone_keys": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "sentiment",
                "engagement",
                "complexity",
                "outcome",
                "satisfaction",
            ],
        },
    )


def _profile_signal_tool() -> dict[str, Any]:
    return _function_tool(
        _PROFILE_SIGNAL_TOOL_NAME,
        "Submit an explicit user profile or communication preference candidate.",
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "trait_family": {
                    "type": "string",
                    "enum": [
                        "identity_profile",
                        "communication_profile",
                        "preference_profile",
                        "routine_profile",
                        "state_profile",
                    ],
                },
                "trait_name": {"type": "string"},
                "trait_value": {"type": "string"},
                "evidence_text": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
            "required": [
                "trait_family",
                "trait_name",
                "trait_value",
                "evidence_text",
                "confidence",
            ],
        },
    )


def _task_preference_tool() -> dict[str, Any]:
    return _function_tool(
        _TASK_PREFERENCE_TOOL_NAME,
        "Submit an explicit future task-handling preference candidate.",
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "task_category": {"type": "string"},
                "preference": {"type": "string"},
                "polarity": {"type": "string", "enum": ["prefer", "avoid"]},
                "evidence_text": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
            "required": [
                "task_category",
                "preference",
                "polarity",
                "evidence_text",
                "confidence",
            ],
        },
    )


def _relationship_signal_tool() -> dict[str, Any]:
    return _function_tool(
        _RELATIONSHIP_SIGNAL_TOOL_NAME,
        "Submit a persona-specific relationship or milestone signal candidate.",
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "signal_type": {
                    "type": "string",
                    "enum": ["trust_delta", "boundary", "milestone"],
                },
                "milestone_key": {"type": "string"},
                "trust_delta": {"type": "number", "minimum": -0.2, "maximum": 0.2},
                "evidence_text": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            },
            "required": ["signal_type", "evidence_text", "confidence"],
        },
    )


def _preview(text: str, limit: int = 240) -> str:
    return " ".join(str(text or "").split())[:limit]


def _diagnostic_preview(text: str, limit: int = 240) -> str:
    if not full_content_logging_enabled():
        return "[content omitted by diagnostics setting]"
    return _preview(text, limit)


def _stp_rule_types(stp_rules: List[Dict[str, str]] | None) -> list[str]:
    return [
        str(rule.get("trigger_type") or "").strip()
        for rule in (stp_rules or [])
        if str(rule.get("trigger_type") or "").strip()
    ]


def _can_use_tool_observer(bridge: LLMProviderBridge) -> bool:
    method = getattr(bridge, "chat_with_tools", None)
    return inspect.iscoroutinefunction(method)


async def _analyze_with_tools(
    bridge: LLMProviderBridge,
    *,
    user_prompt: str,
    stp_rules: List[Dict[str, str]] | None = None,
    milestone_conditions: Dict[str, str] | None = None,
) -> tuple[InteractionAnalysis | None, ProviderResponse]:
    response = await bridge.chat_with_tools(
        system_prompt=_build_tool_system_prompt(stp_rules, milestone_conditions),
        messages=[{"role": "user", "content": user_prompt}],
        tools=_observer_tools(),
        max_tokens=256,
        temperature=0.1,
        disable_thinking=True,
        event_context={
            "request_kind": "personality:interaction_analysis",
            "agent_id": "personality:interaction_analyzer",
        },
    )
    analysis_payload: dict[str, Any] | None = None
    observations: list[InteractionObservation] = []
    for tool_call in list(response.tool_calls or []):
        name = str(getattr(tool_call, "name", "") or "").strip()
        args = getattr(tool_call, "arguments", None)
        if not isinstance(args, dict):
            args = {}
        if name == _ANALYSIS_TOOL_NAME and analysis_payload is None:
            analysis_payload = dict(args)
            continue
        kind = _OBSERVATION_TOOL_KINDS.get(name)
        if kind is None:
            continue
        observations.append(
            InteractionObservation(kind=kind, arguments=_compact_observation_args(args))
        )
        if len(observations) >= 3:
            break

    if analysis_payload is None:
        return None, response
    raw = json.dumps(analysis_payload, ensure_ascii=False)
    analysis = parse_analysis(raw, stp_rules=stp_rules)
    return _with_memory_observations(analysis, observations), response


def _compact_observation_args(args: dict[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    for key, value in args.items():
        key_text = str(key or "").strip()
        if not key_text:
            continue
        if isinstance(value, str):
            text = " ".join(value.split())
            if text:
                compacted[key_text] = text[:500]
        elif isinstance(value, (int, float, bool)) or value is None:
            compacted[key_text] = value
        elif isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
            compacted[key_text] = items[:10]
    return compacted


def _with_memory_observations(
    analysis: InteractionAnalysis,
    observations: list[InteractionObservation],
) -> InteractionAnalysis:
    if not observations:
        return analysis
    return InteractionAnalysis(
        sentiment=analysis.sentiment,
        engagement=analysis.engagement,
        complexity=analysis.complexity,
        outcome=analysis.outcome,
        satisfaction=analysis.satisfaction,
        trigger_type=analysis.trigger_type,
        milestone_keys=list(analysis.milestone_keys),
        memory_observations=list(observations),
    )


async def analyze_interaction(
    user_message: str,
    assistant_response: str,
    stp_rules: List[Dict[str, str]] | None = None,
    milestone_conditions: Dict[str, str] | None = None,
) -> InteractionAnalysis:
    """Analyze a single interaction turn using a lightweight LLM call.

    When *stp_rules* are provided the LLM is also asked to detect whether
    the exchange matches one of the persona's STP trigger conditions.
    When *milestone_conditions* are provided the LLM also checks whether
    any persona-layer milestone conditions are met.

    Returns DEFAULT_ANALYSIS if the LLM call fails or is unavailable.
    """
    bridge = _resolve_analysis_bridge()
    if bridge is None:
        return DEFAULT_ANALYSIS

    user_prompt = _interaction_user_prompt(user_message, assistant_response)
    system_prompt = _build_system_prompt(stp_rules, milestone_conditions)
    started_at = time.monotonic()
    _log_analysis_start(user_message, assistant_response, stp_rules)
    try:
        tool_analysis = await _try_tool_observer(
            bridge,
            user_prompt=user_prompt,
            user_message=user_message,
            assistant_response=assistant_response,
            stp_rules=stp_rules,
            milestone_conditions=milestone_conditions,
            started_at=started_at,
        )
        if tool_analysis is not None:
            return tool_analysis
        return await _analyze_with_json_prompt(
            bridge,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            user_message=user_message,
            assistant_response=assistant_response,
            stp_rules=stp_rules,
            started_at=started_at,
        )
    except Exception:
        _log_analysis_failure(started_at)
        return DEFAULT_ANALYSIS


def _resolve_analysis_bridge() -> LLMProviderBridge | None:
    try:
        pool = get_scenario_llm_pool()
    except Exception:
        return None

    try:
        adapter = pool.get(LLMScenario.CONTEXT_DECIDER)
    except (ValueError, KeyError):
        try:
            adapter = pool.get(LLMScenario.CORE)
        except (ValueError, KeyError):
            return None
    return LLMProviderBridge(adapter)


def _interaction_user_prompt(user_message: str, assistant_response: str) -> str:
    return (
        f"User message:\n{user_message[:500]}\n\n"
        f"Assistant response:\n{assistant_response[:500]}"
    )


def _log_analysis_start(
    user_message: str,
    assistant_response: str,
    stp_rules: List[Dict[str, str]] | None,
) -> None:
    logger.debug(
        "[analyze_interaction] LLM call start user_chars=%d response_chars=%d stp_rule_types=%s",
        len(user_message),
        len(assistant_response),
        _stp_rule_types(stp_rules),
    )


async def _try_tool_observer(
    bridge: LLMProviderBridge,
    *,
    user_prompt: str,
    user_message: str,
    assistant_response: str,
    stp_rules: List[Dict[str, str]] | None,
    milestone_conditions: Dict[str, str] | None,
    started_at: float,
) -> InteractionAnalysis | None:
    if not _can_use_tool_observer(bridge):
        return None
    analysis, response = await _analyze_with_tools(
        bridge,
        user_prompt=user_prompt,
        stp_rules=stp_rules,
        milestone_conditions=milestone_conditions,
    )
    if analysis is None:
        _log_tool_observer_fallback(response)
        return None
    _log_tool_analysis_success(
        analysis,
        user_message=user_message,
        assistant_response=assistant_response,
        stp_rules=stp_rules,
        started_at=started_at,
    )
    return analysis


def _log_tool_observer_fallback(response: ProviderResponse) -> None:
    logger.debug(
        "[analyze_interaction] tool observer returned no analysis; falling back content=%s tool_calls=%s",
        _diagnostic_preview(response.content),
        [getattr(call, "name", "") for call in list(response.tool_calls or [])],
    )


def _log_tool_analysis_success(
    analysis: InteractionAnalysis,
    *,
    user_message: str,
    assistant_response: str,
    stp_rules: List[Dict[str, str]] | None,
    started_at: float,
) -> None:
    elapsed_ms = (time.monotonic() - started_at) * 1000
    logger.info(
        "[analyze_interaction] tool result elapsed_ms=%.1f trigger_type=%s "
        "outcome=%s satisfaction=%s milestone_keys=%s observation_count=%d "
        "stp_rule_types=%s user_preview=%s response_preview=%s",
        elapsed_ms,
        analysis.trigger_type,
        analysis.outcome_str,
        analysis.satisfaction.value,
        analysis.milestone_keys,
        len(analysis.memory_observations),
        _stp_rule_types(stp_rules),
        _diagnostic_preview(user_message),
        _diagnostic_preview(assistant_response),
    )


async def _analyze_with_json_prompt(
    bridge: LLMProviderBridge,
    *,
    system_prompt: str,
    user_prompt: str,
    user_message: str,
    assistant_response: str,
    stp_rules: List[Dict[str, str]] | None,
    started_at: float,
) -> InteractionAnalysis:
    raw = await bridge.chat(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=256,
        temperature=0.1,
        json_mode=True,
        disable_thinking=True,
        event_context={
            "request_kind": "personality:interaction_analysis",
            "agent_id": "personality:interaction_analyzer",
        },
    )
    analysis = parse_analysis(raw, stp_rules=stp_rules)
    _log_json_analysis_success(
        analysis,
        raw=raw,
        user_message=user_message,
        assistant_response=assistant_response,
        stp_rules=stp_rules,
        started_at=started_at,
    )
    return analysis


def _log_json_analysis_success(
    analysis: InteractionAnalysis,
    *,
    raw: str,
    user_message: str,
    assistant_response: str,
    stp_rules: List[Dict[str, str]] | None,
    started_at: float,
) -> None:
    elapsed_ms = (time.monotonic() - started_at) * 1000
    logger.info(
        "[analyze_interaction] result elapsed_ms=%.1f trigger_type=%s outcome=%s "
        "satisfaction=%s milestone_keys=%s stp_rule_types=%s raw_preview=%s "
        "user_preview=%s response_preview=%s",
        elapsed_ms,
        analysis.trigger_type,
        analysis.outcome_str,
        analysis.satisfaction.value,
        analysis.milestone_keys,
        _stp_rule_types(stp_rules),
        _diagnostic_preview(raw),
        _diagnostic_preview(user_message),
        _diagnostic_preview(assistant_response),
    )


def _log_analysis_failure(started_at: float) -> None:
    elapsed_ms = (time.monotonic() - started_at) * 1000
    logger.warning(
        "[analyze_interaction] LLM call failed elapsed_ms=%.1f",
        elapsed_ms,
        exc_info=True,
    )


def parse_analysis(
    raw: str,
    stp_rules: List[Dict[str, str]] | None = None,
) -> InteractionAnalysis:
    """Parse the JSON response from the LLM into an InteractionAnalysis.

    Valid trigger types are derived dynamically from *stp_rules* so that
    persona-defined triggers are accepted without a hardcoded whitelist.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return DEFAULT_ANALYSIS

    try:
        sentiment = _clamp(float(data.get("sentiment", 0.0)), -1.0, 1.0)
    except (ValueError, TypeError):
        sentiment = 0.0

    try:
        complexity = _clamp(float(data.get("complexity", 0.5)), 0.0, 1.0)
    except (ValueError, TypeError):
        complexity = 0.5

    engagement = _ENGAGEMENT_MAP.get(data.get("engagement", ""), EngagementLevel.MEDIUM)
    outcome = _OUTCOME_MAP.get(data.get("outcome", ""), InteractionOutcome.SUCCESS)
    satisfaction = _SATISFACTION_MAP.get(data.get("satisfaction", ""), SatisfactionLevel.NEUTRAL)

    raw_trigger = data.get("trigger_type")
    trigger_type: Optional[str] = None
    if isinstance(raw_trigger, str) and raw_trigger:
        valid_triggers: frozenset[str] = frozenset()
        if stp_rules:
            valid_triggers = frozenset(
                rule["trigger_type"] for rule in stp_rules if rule.get("trigger_type")
            )
        if valid_triggers and raw_trigger in valid_triggers:
            trigger_type = raw_trigger

    raw_milestones = data.get("milestone_keys")
    milestone_keys: List[str] = []
    if isinstance(raw_milestones, list):
        milestone_keys = [k for k in raw_milestones if isinstance(k, str) and k]

    return InteractionAnalysis(
        sentiment=sentiment,
        engagement=engagement,
        complexity=complexity,
        outcome=outcome,
        satisfaction=satisfaction,
        trigger_type=trigger_type,
        milestone_keys=milestone_keys,
    )


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
