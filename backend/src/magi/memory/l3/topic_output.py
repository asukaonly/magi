"""LLM output parsing helpers for L3 thematic topic summaries."""

from __future__ import annotations

from typing import Any

from .models import (
    L3Candidate,
    ThematicEvidencePack,
    ThematicSummaryLLMOutput,
)


class TopicOutputParsingMixin:
    """Parse and validate structured thematic topic summary LLM output."""

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

    def _normalize_importance_aggregate(self, value: Any) -> float | None:
        if value is None:
            return None
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError("importance_aggregate must be between 0.0 and 1.0")
        return numeric


__all__ = ["TopicOutputParsingMixin"]
