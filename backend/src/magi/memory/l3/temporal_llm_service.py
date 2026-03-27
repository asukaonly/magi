"""Rule-side helpers for temporal L3 LLM summarization."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import Counter
from typing import Any

from ...llm import LLMProviderBridge, LLMScenario, ScenarioLLMPool
from .models import (
    L3Candidate,
    TemporalEvidenceItem,
    TemporalEvidencePack,
    TemporalGenerationResult,
    TemporalSummaryLLMOutput,
)

logger = logging.getLogger(__name__)
_TOP_TERM_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_STOP_TERMS = {
    "about",
    "after",
    "and",
    "are",
    "care",
    "but",
    "for",
    "from",
    "have",
    "into",
    "job",
    "jobs",
    "just",
    "more",
    "posts",
    "read",
    "several",
    "than",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "want",
    "with",
    "year",
    "you",
    "your",
}
_CONSTRAINT_KEYWORDS = {
    "avoid",
    "budget",
    "cannot",
    "deadline",
    "hybrid",
    "must",
    "need",
    "prefer",
    "priority",
    "remote",
    "salary",
    "should",
    "time",
}

TEMPORAL_SUMMARY_SYSTEM_PROMPT = """You generate temporal memory summaries for a local-first agent.

Rules:
- Use only the supplied evidence pack.
- Compress repetition and surface concrete changes, priorities, and recurring patterns.
- Do not invent entity ids, event ids, preferences, or psychological diagnoses.
- Return a JSON object with: content, key_topics, key_entities, sentiment_summary, change_and_pattern, importance_aggregate.
- If evidence is weak, stay conservative and summarize only explicit content.
"""
TEMPORAL_SUMMARY_OUTPUT_SCHEMA = {
    "content": "A concise temporal recap grounded in the evidence pack.",
    "key_topics": ["short_topic_label"],
    "key_entities": [{"entity_id": "optional_entity_id", "entity_type": "optional_entity_type"}],
    "sentiment_summary": {"tone": "optional_tone", "stress_level": 0.0},
    "change_and_pattern": {
        "changes": ["explicit shift observed in the window"],
        "patterns": ["recurring behavior or constraint grounded in evidence"],
    },
    "importance_aggregate": 0.0,
}


class TemporalSummaryLLMService:
    """Builds temporal evidence packs and later will host LLM generation helpers."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        llm_timeout_seconds: float = 3.0,
        min_event_count_for_llm: int = 2,
        scenario_llm_pool: ScenarioLLMPool | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._llm_timeout_seconds = float(llm_timeout_seconds)
        self._min_event_count_for_llm = max(1, int(min_event_count_for_llm))
        self._scenario_llm_pool = scenario_llm_pool

    def build_evidence_pack(
        self,
        *,
        events: list[dict[str, Any]],
        summary_category: str,
        period_start: float,
        period_end: float,
    ) -> TemporalEvidencePack:
        """Build a compact evidence pack from already-fetched L1 events."""
        kept_events = [
            event
            for event in events
            if str(event.get("memory_domain") or "") != "runtime_telemetry"
            and str(event.get("retention_class") or "") != "disposable"
        ]
        evidence_items = [
            TemporalEvidenceItem(
                event_id=str(event.get("event_id") or ""),
                event_type=str(event.get("event_type") or ""),
                content=str(event.get("content") or ""),
                timestamp=float(event["timestamp"]) if event.get("timestamp") is not None else None,
                memory_domain=str(event.get("memory_domain") or "") or None,
                importance_score=float(event["importance_score"]) if event.get("importance_score") is not None else None,
            )
            for event in kept_events
            if str(event.get("event_id") or "").strip()
        ]
        source_event_ids = [item.event_id for item in evidence_items]
        importance_values = [item.importance_score for item in evidence_items if item.importance_score is not None]
        event_type_distribution: dict[str, int] = {}
        for item in evidence_items:
            event_type_distribution[item.event_type] = event_type_distribution.get(item.event_type, 0) + 1
        return TemporalEvidencePack(
            summary_category=summary_category,  # type: ignore[arg-type]
            period_start=float(period_start),
            period_end=float(period_end),
            source_event_count=len(source_event_ids),
            source_event_ids=source_event_ids,
            events=evidence_items,
            importance_aggregate=(sum(importance_values) / len(importance_values)) if importance_values else None,
            event_type_distribution=event_type_distribution,
            rule_hints=self._build_rule_hints(evidence_items, event_type_distribution),
        )

    def parse_llm_output(
        self,
        payload: dict[str, Any],
        *,
        pack: TemporalEvidencePack,
    ) -> tuple[L3Candidate, dict[str, Any]]:
        """Parse structured temporal LLM output into an L3 candidate and summary overrides."""
        content = str(payload.get("content") or "").strip()
        if not content:
            raise ValueError("Temporal LLM output requires non-empty content")
        output = TemporalSummaryLLMOutput(
            content=content,
            key_topics=[str(item).strip() for item in payload.get("key_topics", []) if str(item).strip()],
            key_entities=[
                item
                for item in payload.get("key_entities", [])
                if isinstance(item, dict)
            ],
            sentiment_summary=self._normalize_sentiment_summary(payload.get("sentiment_summary")),
            change_and_pattern=self._normalize_change_and_pattern(payload.get("change_and_pattern")),
            importance_aggregate=self._normalize_importance_aggregate(payload.get("importance_aggregate")),
        )
        candidate = L3Candidate(
            summary_type="temporal",
            summary_category=pack.summary_category,
            content=output.content,
            source_event_ids=list(pack.source_event_ids),
        )
        summary_overrides: dict[str, Any] = {
            "key_topics": list(output.key_topics),
            "key_entities": list(output.key_entities),
            "sentiment_summary": output.sentiment_summary,
            "importance_aggregate": output.importance_aggregate,
            "change_and_pattern": output.change_and_pattern,
        }
        return candidate, summary_overrides

    async def generate_temporal_candidate(
        self,
        pack: TemporalEvidencePack,
        *,
        fallback_summary: str,
    ) -> TemporalGenerationResult:
        """Try the model path and fall back to a rule summary on failure."""
        fallback = self._build_fallback_result(pack, fallback_summary)
        if not self._enabled:
            return fallback
        if pack.source_event_count < self._min_event_count_for_llm:
            return fallback
        try:
            payload = await asyncio.wait_for(
                self._call_temporal_model(pack),
                timeout=self._llm_timeout_seconds,
            )
        except Exception:
            return fallback
        if not isinstance(payload, dict):
            return fallback
        try:
            candidate, summary_overrides = self.parse_llm_output(payload, pack=pack)
        except Exception:
            return fallback
        return TemporalGenerationResult(
            candidate=candidate,
            summary_overrides=summary_overrides,
            used_fallback=False,
        )

    async def _call_temporal_model(self, pack: TemporalEvidencePack) -> dict[str, Any] | None:
        """Model hook for temporal summary generation.

        The default implementation is intentionally inert until a real LLM caller
        is wired in by a later task.
        """
        llm_target = self._get_llm_target()
        if llm_target is None:
            return None
        adapter, provider_bridge = llm_target
        prompt = self._render_temporal_summary_prompt(pack)
        started_at = time.perf_counter()
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        log_context = {
            "request_kind": "memory:l3_temporal_summary",
            "provider": provider,
            "model": model,
            "event_count": pack.source_event_count,
            "summary_category": pack.summary_category,
        }
        logger.info("L3 temporal LLM call started", extra=log_context)
        try:
            response = await provider_bridge.chat_response(
                system_prompt=TEMPORAL_SUMMARY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True,
                disable_thinking=True,
                timeout_seconds=self._llm_timeout_seconds,
                event_context={
                    "request_kind": "memory:l3_temporal_summary",
                    "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                    "agent_id": "memory:l3",
                },
            )
        except Exception as exc:
            logger.warning("L3 temporal LLM call failed", extra={**log_context, "error": str(exc)})
            raise

        raw = response.content
        logger.info(
            "L3 temporal LLM call completed",
            extra={
                **log_context,
                "duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
                "response_char_count": len(raw or ""),
            },
        )
        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning("L3 temporal LLM returned invalid JSON", extra=log_context)
            return None
        return parsed if isinstance(parsed, dict) else None

    def _build_fallback_result(
        self,
        pack: TemporalEvidencePack,
        fallback_summary: str,
    ) -> TemporalGenerationResult:
        candidate = L3Candidate(
            summary_type="temporal",
            summary_category=pack.summary_category,
            content=str(fallback_summary).strip(),
            source_event_ids=list(pack.source_event_ids),
        )
        summary_overrides: dict[str, object] = {
            "importance_aggregate": pack.importance_aggregate,
            "event_type_distribution": dict(pack.event_type_distribution),
        }
        feature_lines: list[str] = []
        for feature in pack.plugin_summary_features.values():
            if not isinstance(feature, dict):
                continue
            raw_lines = feature.get("summary_lines")
            if not isinstance(raw_lines, list):
                continue
            for item in raw_lines:
                line = str(item).strip()
                if line and line not in feature_lines:
                    feature_lines.append(line)
        if feature_lines:
            stitched = [str(fallback_summary).strip(), *feature_lines]
            candidate.content = "\n".join(part for part in stitched if part).strip()
            summary_overrides["plugin_summary_features"] = dict(pack.plugin_summary_features)
        return TemporalGenerationResult(
            candidate=candidate,
            summary_overrides=summary_overrides,
            used_fallback=True,
        )

    def _render_temporal_summary_prompt(self, pack: TemporalEvidencePack) -> str:
        payload = {
            "summary_type": "temporal",
            "summary_category": pack.summary_category,
            "period_start": pack.period_start,
            "period_end": pack.period_end,
            "source_event_count": pack.source_event_count,
            "source_event_ids": pack.source_event_ids,
            "importance_aggregate": pack.importance_aggregate,
            "event_type_distribution": pack.event_type_distribution,
            "rule_hints": pack.rule_hints,
            "plugin_summary_features": pack.plugin_summary_features,
            "events": [
                {
                    "event_id": item.event_id,
                    "event_type": item.event_type,
                    "timestamp": item.timestamp,
                    "memory_domain": item.memory_domain,
                    "importance_score": item.importance_score,
                    "content": item.content,
                }
                for item in pack.events
            ],
        }
        schema = json.dumps(TEMPORAL_SUMMARY_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
        evidence = json.dumps(payload, ensure_ascii=False, indent=2)
        return (
            "Task:\n"
            "Write a temporal summary for the provided memory window.\n"
            "Use the rule_hints as guidance, not as independent evidence.\n"
            "Prioritize explicit changes, recurring constraints, and high-importance events.\n\n"
            "Output Requirements:\n"
            "- Return one JSON object only.\n"
            "- Keep content concise and evidence-grounded.\n"
            "- Use empty lists or nulls when a field has no support.\n\n"
            "Output JSON Schema:\n"
            f"{schema}\n\n"
            "Evidence Pack:\n"
            f"{evidence}\n"
        )

    def _get_adapter(self) -> Any | None:
        if self._scenario_llm_pool is None:
            return None
        try:
            return self._scenario_llm_pool.get(LLMScenario.CONTEXT_DECIDER)
        except Exception as exc:
            logger.debug("L3 temporal LLM adapter unavailable: %s", exc)
            return None

    def _get_llm_target(self) -> tuple[Any, LLMProviderBridge] | None:
        adapter = self._get_adapter()
        if adapter is None:
            return None
        return adapter, LLMProviderBridge(adapter)

    def _normalize_importance_aggregate(self, value: Any) -> float | None:
        if value is None:
            return None
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError("importance_aggregate must be between 0.0 and 1.0")
        return numeric

    def _normalize_sentiment_summary(self, value: Any) -> dict[str, object] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("sentiment_summary must be an object")
        normalized: dict[str, object] = {}
        for key, item in value.items():
            key_str = str(key).strip()
            if not key_str:
                continue
            if key_str == "stress_level":
                stress_level = float(item)
                if stress_level < 0.0 or stress_level > 1.0:
                    raise ValueError("sentiment_summary.stress_level must be between 0.0 and 1.0")
                normalized[key_str] = stress_level
                continue
            if isinstance(item, (str, int, float, bool)) or item is None:
                normalized[key_str] = item
        return normalized or None

    def _normalize_change_and_pattern(self, value: Any) -> dict[str, object] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("change_and_pattern must be an object")
        normalized: dict[str, object] = {}
        for key in ("changes", "patterns"):
            raw = value.get(key)
            if raw is None:
                continue
            if not isinstance(raw, list) or any(not str(item).strip() for item in raw):
                raise ValueError(f"change_and_pattern.{key} must be a list of non-empty strings")
            normalized[key] = [str(item).strip() for item in raw]
        for key, item in value.items():
            if key in normalized or key in {"changes", "patterns"}:
                continue
            if isinstance(item, (str, int, float, bool)) or item is None:
                normalized[str(key)] = item
        return normalized or None

    def _build_rule_hints(
        self,
        evidence_items: list[TemporalEvidenceItem],
        event_type_distribution: dict[str, int],
    ) -> dict[str, object]:
        term_counter: Counter[str] = Counter()
        for item in evidence_items:
            for token in _TOP_TERM_PATTERN.findall(item.content.lower()):
                if token in _STOP_TERMS:
                    continue
                term_counter[token] += 1
        high_importance_event_ids = [
            item.event_id
            for item in sorted(
                evidence_items,
                key=lambda candidate: float(candidate.importance_score or 0.0),
                reverse=True,
            )[:3]
            if item.event_id
        ]
        repeated_event_types = [
            event_type
            for event_type, count in sorted(event_type_distribution.items())
            if count > 1
        ]
        ordered_items = sorted(
            evidence_items,
            key=lambda item: (float(item.timestamp) if item.timestamp is not None else float("inf")),
        )
        window_change_candidates = self._build_window_change_candidates(ordered_items)
        recurring_constraints = self._build_recurring_constraints(evidence_items)
        return {
            "top_terms": [term for term, _count in term_counter.most_common(5)],
            "high_importance_event_ids": high_importance_event_ids,
            "repeated_event_types": repeated_event_types,
            "window_change_candidates": window_change_candidates,
            "recurring_constraints": recurring_constraints,
        }

    def _build_window_change_candidates(
        self,
        evidence_items: list[TemporalEvidenceItem],
    ) -> list[dict[str, object]]:
        if len(evidence_items) < 2:
            return []
        early_terms = self._extract_ranked_terms(evidence_items[0].content)[:3]
        late_terms = self._extract_ranked_terms(evidence_items[-1].content)[:3]
        new_terms = [term for term in late_terms if term not in early_terms][:3]
        dropped_terms = [term for term in early_terms if term not in late_terms][:3]
        if not early_terms and not late_terms:
            return []
        return [
            {
                "kind": "first_last_focus_shift",
                "from_event_id": evidence_items[0].event_id,
                "to_event_id": evidence_items[-1].event_id,
                "early_terms": early_terms,
                "late_terms": late_terms,
                "new_terms": new_terms,
                "dropped_terms": dropped_terms,
            }
        ]

    def _build_recurring_constraints(
        self,
        evidence_items: list[TemporalEvidenceItem],
    ) -> list[dict[str, object]]:
        hits: dict[str, list[str]] = {}
        for item in evidence_items:
            content = item.content.lower()
            matched = [keyword for keyword in _CONSTRAINT_KEYWORDS if keyword in content]
            for keyword in matched:
                hits.setdefault(keyword, [])
                if item.event_id not in hits[keyword]:
                    hits[keyword].append(item.event_id)
        recurring = [
            {
                "keyword": keyword,
                "event_ids": event_ids,
            }
            for keyword, event_ids in sorted(hits.items())
            if len(event_ids) >= 2
        ]
        return recurring

    def _extract_ranked_terms(self, content: str) -> list[str]:
        counter: Counter[str] = Counter()
        for token in _TOP_TERM_PATTERN.findall(content.lower()):
            if token in _STOP_TERMS:
                continue
            counter[token] += 1
        return [term for term, _count in counter.most_common(5)]
