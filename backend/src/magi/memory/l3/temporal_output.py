"""LLM output parsing helpers for L3 temporal summaries."""

from __future__ import annotations

from typing import Any

from .models import (
    L3Candidate,
    TemporalEvidencePack,
    TemporalSummaryLLMOutput,
)


_CHANGE_AND_PATTERN_LIST_FIELDS = (
    "timeline",
    "source_signals",
    "decisions_and_actions",
    "changes",
    "patterns",
    "open_threads",
    "daily_breakdown",
    "weekly_breakdown",
)
_CHANGE_AND_PATTERN_NESTED_DICT_FIELDS = (
    "trend_shifts",
    "metrics",
)


class TemporalOutputParsingMixin:
    """Parse and validate structured temporal summary LLM output."""

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
        validator = getattr(self, "_validate_target_language", None)
        if callable(validator):
            validator(output)
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
            "change_and_pattern": output.change_and_pattern,
        }
        if output.importance_aggregate is not None:
            summary_overrides["importance_aggregate"] = output.importance_aggregate
        return candidate, summary_overrides

    def parse_structure_output(
        self,
        payload: dict[str, Any],
        *,
        pack: TemporalEvidencePack,
        content: str,
    ) -> dict[str, Any]:
        """Parse optional structured fields after user-facing prose is accepted."""
        content = str(content or "").strip()
        if not content:
            raise ValueError("Temporal structure output requires accepted content")
        payload_content = payload.get("content")
        if payload_content is not None:
            normalized_payload_content = str(payload_content).strip()
            if normalized_payload_content and normalized_payload_content != content:
                raise ValueError("Temporal structure content must match accepted content")
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
        validator = getattr(self, "_validate_target_language", None)
        if callable(validator):
            validator(output)
        summary_overrides: dict[str, Any] = {
            "key_topics": list(output.key_topics),
            "key_entities": list(output.key_entities),
            "sentiment_summary": output.sentiment_summary,
            "change_and_pattern": output.change_and_pattern,
        }
        if output.importance_aggregate is not None:
            summary_overrides["importance_aggregate"] = output.importance_aggregate
        return summary_overrides

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
        for key in _CHANGE_AND_PATTERN_LIST_FIELDS:
            raw = value.get(key)
            if raw is None:
                continue
            if not isinstance(raw, list) or any(not str(item).strip() for item in raw):
                raise ValueError(f"change_and_pattern.{key} must be a list of non-empty strings")
            normalized[key] = [str(item).strip() for item in raw]
        for key in _CHANGE_AND_PATTERN_NESTED_DICT_FIELDS:
            raw = value.get(key)
            if raw is None:
                continue
            if not isinstance(raw, dict):
                raise ValueError(f"change_and_pattern.{key} must be an object")
            nested: dict[str, object] = {}
            for inner_key, inner_value in raw.items():
                inner_key_str = str(inner_key).strip()
                if not inner_key_str:
                    continue
                if isinstance(inner_value, list):
                    if any(not str(entry).strip() for entry in inner_value):
                        raise ValueError(
                            f"change_and_pattern.{key}.{inner_key_str} must be a list of non-empty strings"
                        )
                    nested[inner_key_str] = [str(entry).strip() for entry in inner_value]
                    continue
                if isinstance(inner_value, (str, int, float, bool)) or inner_value is None:
                    nested[inner_key_str] = inner_value
            if nested:
                normalized[key] = nested
        for key, item in value.items():
            if (
                key in normalized
                or key in _CHANGE_AND_PATTERN_LIST_FIELDS
                or key in _CHANGE_AND_PATTERN_NESTED_DICT_FIELDS
            ):
                continue
            key_str = str(key).strip()
            if not key_str:
                continue
            if isinstance(item, list):
                if any(not str(entry).strip() for entry in item):
                    raise ValueError(f"change_and_pattern.{key_str} must be a list of non-empty strings")
                normalized[key_str] = [str(entry).strip() for entry in item]
                continue
            if isinstance(item, (str, int, float, bool)) or item is None:
                normalized[key_str] = item
        return normalized or None


__all__ = ["TemporalOutputParsingMixin"]
