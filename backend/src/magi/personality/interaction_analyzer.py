"""Lightweight LLM-based interaction quality analyzer."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..config.models import LLMScenario
from ..core.logger import get_logger
from ..core.runtime_bindings import require_scenario_llm_pool
from ..llm.provider_bridge import LLMProviderBridge
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
                + ' if a trigger condition is clearly matched, or null if none applies. '
                'Only activate a trigger when the conversation clearly matches the described condition.'
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
                + ') that are clearly achieved in this exchange, or an empty array if none. '
                'Only mark a milestone when the exchange unmistakably demonstrates '
                'the described condition — do not mark it for vague similarity.'
            )

    if not extra:
        return _SYSTEM_PROMPT
    return _SYSTEM_PROMPT + extra


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
    try:
        pool = require_scenario_llm_pool()
    except Exception:
        return DEFAULT_ANALYSIS

    try:
        adapter = pool.get(LLMScenario.CONTEXT_DECIDER)
    except (ValueError, KeyError):
        try:
            adapter = pool.get(LLMScenario.CORE)
        except (ValueError, KeyError):
            return DEFAULT_ANALYSIS

    bridge = LLMProviderBridge(adapter)
    user_prompt = (
        f"User message:\n{user_message[:500]}\n\n"
        f"Assistant response:\n{assistant_response[:500]}"
    )

    system_prompt = _build_system_prompt(stp_rules, milestone_conditions)

    t0 = time.monotonic()
    logger.debug(
        "[analyze_interaction] LLM call start user_chars=%d response_chars=%d",
        len(user_message),
        len(assistant_response),
    )
    try:
        raw = await bridge.chat(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=256,
            temperature=0.1,
            json_mode=True,
            disable_thinking=True,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.debug("[analyze_interaction] LLM call completed elapsed_ms=%.1f", elapsed_ms)
        return parse_analysis(raw, stp_rules=stp_rules)
    except Exception:
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.warning(
            "[analyze_interaction] LLM call failed elapsed_ms=%.1f",
            elapsed_ms,
            exc_info=True,
        )
        return DEFAULT_ANALYSIS


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

    engagement = _ENGAGEMENT_MAP.get(
        data.get("engagement", ""), EngagementLevel.MEDIUM
    )
    outcome = _OUTCOME_MAP.get(
        data.get("outcome", ""), InteractionOutcome.SUCCESS
    )
    satisfaction = _SATISFACTION_MAP.get(
        data.get("satisfaction", ""), SatisfactionLevel.NEUTRAL
    )

    raw_trigger = data.get("trigger_type")
    trigger_type: Optional[str] = None
    if isinstance(raw_trigger, str) and raw_trigger:
        valid_triggers: frozenset[str] = frozenset()
        if stp_rules:
            valid_triggers = frozenset(
                rule["trigger_type"] for rule in stp_rules
                if rule.get("trigger_type")
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
