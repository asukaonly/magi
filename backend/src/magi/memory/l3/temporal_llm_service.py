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

TEMPORAL_SUMMARY_SYSTEM_PROMPT = """You generate temporal memory summaries for a local-first agent.

Rules:
- Use only the supplied evidence pack.
- Compress repetition and surface concrete changes, priorities, and recurring patterns.
- Do not invent entity ids, event ids, preferences, or psychological diagnoses.
- Return a JSON object with: content, key_topics, key_entities, sentiment_summary, change_and_pattern, importance_aggregate.
- If evidence is weak, stay conservative and summarize only explicit content.
"""


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
                content=str(event.get("raw_content") or ""),
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
            sentiment_summary=payload.get("sentiment_summary") if isinstance(payload.get("sentiment_summary"), dict) else None,
            change_and_pattern=payload.get("change_and_pattern") if isinstance(payload.get("change_and_pattern"), dict) else None,
            importance_aggregate=float(payload["importance_aggregate"]) if payload.get("importance_aggregate") is not None else None,
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
        return json.dumps(payload, ensure_ascii=False, indent=2)

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
        return {
            "top_terms": [term for term, _count in term_counter.most_common(5)],
            "high_importance_event_ids": high_importance_event_ids,
            "repeated_event_types": repeated_event_types,
        }
