"""Shared interaction-analysis contracts and parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config.models import LLMScenario
from ..llm.provider import get_scenario_llm_pool
from ..llm.provider_bridge import LLMProviderBridge
from .models import SatisfactionLevel
from .emotional_state import EngagementLevel, InteractionOutcome

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
class InteractionObservation:
    """Structured post-turn observation emitted by the interaction analyzer."""

    kind: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InteractionAnalysis:
    """Result of analyzing a single user-assistant interaction turn."""

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


def _resolve_analysis_bridge() -> LLMProviderBridge | None:
    try:
        pool = get_scenario_llm_pool()
    except Exception:
        return None

    try:
        adapter = pool.get(LLMScenario.AUXILIARY)
    except (ValueError, KeyError):
        try:
            adapter = pool.get(LLMScenario.CORE)
        except (ValueError, KeyError):
            return None
    return LLMProviderBridge(adapter)


def parse_analysis(
    raw: str,
    stp_rules: List[Dict[str, str]] | None = None,
) -> InteractionAnalysis:
    """Parse a batch-analysis row into a validated interaction result."""
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
    satisfaction = _SATISFACTION_MAP.get(
        data.get("satisfaction", ""),
        SatisfactionLevel.NEUTRAL,
    )

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
        milestone_keys = [
            key for key in raw_milestones if isinstance(key, str) and key
        ]

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
