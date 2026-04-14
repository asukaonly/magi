"""L4 strategy extraction: LLM-driven distillation of execution traces."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ...config.models import LLMScenario

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """\
You are analyzing tool/workflow execution history for an AI agent.
Your task is to distill actionable execution strategies from accumulated traces.

Rules:
- Focus on patterns, not individual events.
- Be specific and actionable.
- Keep each point concise (one sentence).
- If there are too few traces or no clear pattern, return minimal content.
- Respond in the same language as the trace content.

Respond with a single valid JSON object. No markdown, no explanation outside the JSON.

JSON structure:
{
  "best_use_cases": ["string"],
  "avoid_patterns": ["string"],
  "recommended_approach": "string",
  "context_preferences": {"context_description": relevance_float_0_to_1},
  "failure_patterns": ["string"],
  "confidence": float_0_to_1
}

Field descriptions:
- best_use_cases: When this tool/workflow works well (max 3 items)
- avoid_patterns: When to avoid using it or common mistakes (max 3 items)
- recommended_approach: One-sentence best practice for using this tool
- context_preferences: Map of task context → relevance score (0-1), e.g. {"weather queries": 0.95}
- failure_patterns: Recurring failure modes observed (max 3 items)
- confidence: How confident you are in these recommendations (0-1), based on trace quantity and consistency
"""


@dataclass
class ExtractedStrategy:
    """Result of LLM strategy extraction."""

    best_use_cases: List[str] = field(default_factory=list)
    avoid_patterns: List[str] = field(default_factory=list)
    recommended_approach: str = ""
    context_preferences: Dict[str, float] = field(default_factory=dict)
    failure_patterns: List[str] = field(default_factory=list)
    confidence: float = 0.0
    extracted_from_traces: int = 0
    extracted_at: float = 0.0

    def to_json(self) -> str:
        return json.dumps(
            {
                "best_use_cases": self.best_use_cases,
                "avoid_patterns": self.avoid_patterns,
                "recommended_approach": self.recommended_approach,
                "context_preferences": self.context_preferences,
                "failure_patterns": self.failure_patterns,
                "confidence": self.confidence,
                "extracted_from_traces": self.extracted_from_traces,
                "extracted_at": self.extracted_at,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, text: str) -> "ExtractedStrategy":
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                return cls()
            return cls(
                best_use_cases=list(data.get("best_use_cases") or []),
                avoid_patterns=list(data.get("avoid_patterns") or []),
                recommended_approach=str(data.get("recommended_approach") or ""),
                context_preferences=dict(data.get("context_preferences") or {}),
                failure_patterns=list(data.get("failure_patterns") or []),
                confidence=float(data.get("confidence") or 0.0),
                extracted_from_traces=int(data.get("extracted_from_traces") or 0),
                extracted_at=float(data.get("extracted_at") or 0.0),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            return cls()


def _build_extraction_prompt(
    *,
    skill_name: str,
    skill_category: str,
    total_attempts: int,
    success_rate: float,
    traces: List[Dict[str, Any]],
    duration_baseline: Optional[Dict[str, float]] = None,
) -> str:
    """Build the user prompt for strategy extraction."""
    lines = [
        f"## Tool/Workflow: {skill_name} (category: {skill_category})",
        f"Total attempts: {total_attempts}, Success rate: {success_rate:.0%}",
    ]
    if duration_baseline:
        avg = duration_baseline.get("avg_ms", 0.0)
        p95 = duration_baseline.get("p95_ms", 0.0)
        if avg > 0:
            lines.append(f"Average duration: {avg:.0f}ms, P95 duration: {p95:.0f}ms")
    lines.append("")
    lines.append("## Recent Execution Traces (newest first):")

    for i, t in enumerate(traces, 1):
        status = "SUCCESS" if t.get("success") else "FAILURE"
        duration = t.get("duration_ms") or 0.0
        parts = [f"#{i} [{status}]"]
        if duration > 0:
            parts.append(f"duration={duration:.0f}ms")
            # Flag notably slow executions.
            if duration_baseline:
                p95 = duration_baseline.get("p95_ms", 0.0)
                if p95 > 0 and duration > p95:
                    parts.append("(SLOW)")
        if t.get("task_context"):
            parts.append(f"context={t['task_context']}")
        lines.append(" ".join(parts))
        if t.get("input_summary"):
            lines.append(f"  Input: {t['input_summary']}")
        if t.get("output_summary"):
            lines.append(f"  Output: {t['output_summary']}")
        if t.get("error_summary"):
            lines.append(f"  Error: {t['error_summary']}")
        if t.get("recovery_tool"):
            recovery_line = f"  → Recovery: {t['recovery_tool']} succeeded"
            if t.get("recovery_output"):
                recovery_line += f" with: {t['recovery_output']}"
            lines.append(recovery_line)
        lines.append("")

    lines.append("Based on these execution traces, extract actionable strategy recommendations.")
    return "\n".join(lines)


class L4StrategyExtractor:
    """Extracts execution strategies from accumulated L4 traces via LLM."""

    def __init__(
        self,
        scenario_llm_pool: Any,
    ) -> None:
        self._scenario_llm_pool = scenario_llm_pool

    async def extract_strategy(
        self,
        *,
        skill_name: str,
        skill_category: str,
        total_attempts: int,
        success_rate: float,
        traces: List[Dict[str, Any]],
        duration_baseline: Optional[Dict[str, float]] = None,
    ) -> Optional[ExtractedStrategy]:
        """Call LLM to distill execution traces into an actionable strategy.

        Returns None if LLM is unavailable or extraction fails.
        """
        if not traces:
            return None

        adapter, bridge = self._resolve_llm()
        if adapter is None or bridge is None:
            logger.debug("L4 strategy extraction skipped: no LLM available")
            return None

        prompt = _build_extraction_prompt(
            skill_name=skill_name,
            skill_category=skill_category,
            total_attempts=total_attempts,
            success_rate=success_rate,
            traces=traces,
            duration_baseline=duration_baseline,
        )

        try:
            response = await bridge.chat_response(
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.0,
                json_mode=True,
                disable_thinking=True,
                event_context={
                    "request_kind": "l4_strategy_extraction",
                    "agent_id": "memory:l4",
                },
            )
            content = (response.content or "").strip()
            if not content:
                logger.warning("L4 strategy extraction returned empty response")
                return None

            strategy = _parse_strategy_response(content, trace_count=len(traces))
            logger.info(
                "L4 strategy extracted for %s (confidence=%.2f, traces=%d)",
                skill_name,
                strategy.confidence,
                len(traces),
            )
            return strategy

        except Exception as exc:
            logger.warning("L4 strategy extraction failed for %s: %s", skill_name, exc)
            return None

    def _resolve_llm(self) -> tuple[Any, Any]:
        """Resolve LLM adapter and bridge for extraction."""
        if self._scenario_llm_pool is None:
            return None, None
        try:
            from ...llm import LLMProviderBridge

            adapter = self._scenario_llm_pool.get(LLMScenario.CONTEXT_COMPACT)
            if adapter is None:
                return None, None
            bridge = LLMProviderBridge(adapter)
            return adapter, bridge
        except Exception as exc:
            logger.debug("Failed to resolve LLM for L4 extraction: %s", exc)
            return None, None


def _parse_strategy_response(content: str, *, trace_count: int) -> ExtractedStrategy:
    """Parse LLM JSON response into ExtractedStrategy."""
    try:
        data = json.loads(content)
        if not isinstance(data, dict):
            return ExtractedStrategy(confidence=0.0)
    except (json.JSONDecodeError, TypeError):
        logger.warning("L4 strategy extraction returned invalid JSON")
        return ExtractedStrategy(confidence=0.0)

    return ExtractedStrategy(
        best_use_cases=_str_list(data.get("best_use_cases"), max_items=3),
        avoid_patterns=_str_list(data.get("avoid_patterns"), max_items=3),
        recommended_approach=str(data.get("recommended_approach") or "").strip(),
        context_preferences=_float_dict(data.get("context_preferences")),
        failure_patterns=_str_list(data.get("failure_patterns"), max_items=3),
        confidence=_clamp(float(data.get("confidence") or 0.0), 0.0, 1.0),
        extracted_from_traces=trace_count,
        extracted_at=time.time(),
    )


def _str_list(value: Any, *, max_items: int = 5) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value[:max_items] if str(v).strip()]


def _float_dict(value: Any) -> Dict[str, float]:
    if not isinstance(value, dict):
        return {}
    result: Dict[str, float] = {}
    for k, v in value.items():
        try:
            result[str(k)] = _clamp(float(v), 0.0, 1.0)
        except (TypeError, ValueError):
            continue
    return result


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
