"""Rule-side helpers for thematic L3 topic summarization."""

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
    ThematicEvidenceItem,
    ThematicEvidencePack,
    ThematicGenerationResult,
    ThematicSummaryLLMOutput,
)

logger = logging.getLogger(__name__)
_TOP_TERM_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
_STOP_TERMS = {
    "about",
    "across",
    "after",
    "and",
    "are",
    "first",
    "for",
    "from",
    "into",
    "job",
    "jobs",
    "looks",
    "more",
    "multiple",
    "portfolio",
    "roles",
    "should",
    "stronger",
    "switch",
    "than",
    "that",
    "the",
    "this",
    "want",
    "year",
}

TOPIC_SUMMARY_SYSTEM_PROMPT = """You generate thematic memory summaries for a local-first agent.

Rules:
- Use only the supplied evidence pack.
- Summarize what repeatedly surfaced around the topic and why it matters.
- Treat rule_hints as guidance, not as independent evidence.
- Do not invent entity ids, event ids, or unsupported preferences.
- Return a JSON object with: content, key_topics, key_entities, importance_aggregate.
"""
TOPIC_SUMMARY_OUTPUT_SCHEMA = {
    "content": "A concise thematic recap grounded in the evidence pack.",
    "key_topics": ["short_topic_label"],
    "key_entities": [{"entity_id": "optional_entity_id", "entity_type": "optional_entity_type"}],
    "importance_aggregate": 0.0,
}


class TopicSummaryLLMService:
    """Builds topic evidence packs and supports a fallback-safe LLM path."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        llm_timeout_seconds: float = 3.0,
        scenario_llm_pool: ScenarioLLMPool | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._llm_timeout_seconds = float(llm_timeout_seconds)
        self._scenario_llm_pool = scenario_llm_pool

    def build_evidence_pack(
        self,
        *,
        topic: str,
        events: list[dict[str, Any]],
    ) -> ThematicEvidencePack:
        evidence_items = [
            ThematicEvidenceItem(
                event_id=str(event.get("event_id") or ""),
                event_type=str(event.get("event_type") or ""),
                content=str(event.get("raw_content") or ""),
                timestamp=float(event["timestamp"]) if event.get("timestamp") is not None else None,
                importance_score=float(event["importance_score"]) if event.get("importance_score") is not None else None,
            )
            for event in events
            if str(event.get("event_id") or "").strip()
        ]
        source_event_ids = [item.event_id for item in evidence_items]
        importance_values = [item.importance_score for item in evidence_items if item.importance_score is not None]
        event_type_distribution: dict[str, int] = {}
        for item in evidence_items:
            event_type_distribution[item.event_type] = event_type_distribution.get(item.event_type, 0) + 1
        return ThematicEvidencePack(
            topic=str(topic).strip(),
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
        pack: ThematicEvidencePack,
    ) -> tuple[L3Candidate, dict[str, Any]]:
        content = str(payload.get("content") or "").strip()
        if not content:
            raise ValueError("Thematic LLM output requires non-empty content")
        importance = self._normalize_importance_aggregate(payload.get("importance_aggregate"))
        output = ThematicSummaryLLMOutput(
            content=content,
            key_topics=[str(item).strip() for item in payload.get("key_topics", []) if str(item).strip()],
            key_entities=[item for item in payload.get("key_entities", []) if isinstance(item, dict)],
            importance_aggregate=importance,
        )
        candidate = L3Candidate(
            summary_type="thematic",
            summary_category="topic",
            content=output.content,
            source_event_ids=list(pack.source_event_ids),
        )
        return candidate, {
            "key_topics": list(output.key_topics),
            "key_entities": list(output.key_entities),
            "importance_aggregate": output.importance_aggregate,
        }

    async def generate_topic_candidate(
        self,
        pack: ThematicEvidencePack,
        *,
        fallback_summary: str,
    ) -> ThematicGenerationResult:
        fallback = self._build_fallback_result(pack, fallback_summary)
        if not self._enabled:
            return fallback
        try:
            payload = await asyncio.wait_for(
                self._call_topic_model(pack),
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
        return ThematicGenerationResult(
            candidate=candidate,
            summary_overrides=summary_overrides,
            used_fallback=False,
        )

    async def _call_topic_model(self, pack: ThematicEvidencePack) -> dict[str, Any] | None:
        llm_target = self._get_llm_target()
        if llm_target is None:
            return None
        adapter, provider_bridge = llm_target
        prompt = self.render_topic_prompt(pack)
        started_at = time.perf_counter()
        provider = str(getattr(adapter, "provider_name", "unknown") or "unknown")
        model = str(getattr(adapter, "model_name", "unknown") or "unknown")
        log_context = {
            "request_kind": "memory:l3_thematic_topic_summary",
            "provider": provider,
            "model": model,
            "event_count": pack.source_event_count,
            "topic": pack.topic,
        }
        logger.info("L3 thematic topic LLM call started", extra=log_context)
        try:
            response = await provider_bridge.chat_response(
                system_prompt=TOPIC_SUMMARY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                json_mode=True,
                disable_thinking=True,
                timeout_seconds=self._llm_timeout_seconds,
                event_context={
                    "request_kind": "memory:l3_thematic_topic_summary",
                    "turn_id": pack.source_event_ids[0] if pack.source_event_ids else None,
                    "agent_id": "memory:l3",
                },
            )
        except Exception as exc:
            logger.warning("L3 thematic topic LLM call failed", extra={**log_context, "error": str(exc)})
            raise

        raw = response.content
        logger.info(
            "L3 thematic topic LLM call completed",
            extra={
                **log_context,
                "duration_ms": round((time.perf_counter() - started_at) * 1000.0, 2),
                "response_char_count": len(raw or ""),
            },
        )
        try:
            parsed = json.loads(raw)
        except Exception:
            logger.warning("L3 thematic topic LLM returned invalid JSON", extra=log_context)
            return None
        return parsed if isinstance(parsed, dict) else None

    def _build_fallback_result(
        self,
        pack: ThematicEvidencePack,
        fallback_summary: str,
    ) -> ThematicGenerationResult:
        candidate = L3Candidate(
            summary_type="thematic",
            summary_category="topic",
            content=str(fallback_summary).strip(),
            source_event_ids=list(pack.source_event_ids),
        )
        return ThematicGenerationResult(
            candidate=candidate,
            summary_overrides={
                "importance_aggregate": pack.importance_aggregate,
                "event_type_distribution": dict(pack.event_type_distribution),
            },
            used_fallback=True,
        )

    def render_topic_prompt(self, pack: ThematicEvidencePack) -> str:
        payload = {
            "summary_type": "thematic",
            "summary_category": "topic",
            "topic": pack.topic,
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
                    "importance_score": item.importance_score,
                    "content": item.content,
                }
                for item in pack.events
            ],
        }
        schema = json.dumps(TOPIC_SUMMARY_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
        evidence = json.dumps(payload, ensure_ascii=False, indent=2)
        return (
            "Task:\n"
            "Write a thematic topic summary for the provided evidence pack.\n"
            "Use the rule_hints as guidance, not as independent evidence.\n"
            "Prioritize repeated concerns, decisions, and high-importance events.\n\n"
            "Output Requirements:\n"
            "- Return one JSON object only.\n"
            "- Keep content concise and evidence-grounded.\n"
            "- Use empty lists when a field has no support.\n\n"
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
            logger.debug("L3 thematic topic LLM adapter unavailable: %s", exc)
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

    def _build_rule_hints(
        self,
        evidence_items: list[ThematicEvidenceItem],
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
            if count > 1 and event_type
        ]
        return {
            "top_terms": [term for term, _count in term_counter.most_common(5)],
            "high_importance_event_ids": high_importance_event_ids,
            "repeated_event_types": repeated_event_types,
        }
