"""Rule-side helpers for temporal L3 LLM summarization."""

from __future__ import annotations

import asyncio
from typing import Any

from .models import (
    L3Candidate,
    TemporalEvidenceItem,
    TemporalEvidencePack,
    TemporalGenerationResult,
    TemporalSummaryLLMOutput,
)


class TemporalSummaryLLMService:
    """Builds temporal evidence packs and later will host LLM generation helpers."""

    def __init__(self, *, enabled: bool = True, llm_timeout_seconds: float = 3.0) -> None:
        self._enabled = bool(enabled)
        self._llm_timeout_seconds = float(llm_timeout_seconds)

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
        _ = pack
        return None

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
