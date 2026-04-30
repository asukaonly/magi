"""Pure policy helpers for HybridRetrievalService."""
from __future__ import annotations

import re
from typing import Any

from .answerability import (
    extract_comparison_spans,
    extract_query_tokens,
    extract_quoted_spans,
    has_temporal_anchor,
)
from .models import RetrievalPayload

_TURN_NUMBER_RE = re.compile(r"turn-(\d+)$")


def plan_signature(plan: Any) -> tuple[str, str, bool]:
    content_query = getattr(getattr(plan, "conditions", None), "content_query", "") or ""
    return (str(getattr(plan, "layer", "")), str(content_query), bool(getattr(plan, "is_fallback", False)))


def count_payload_results(payload: RetrievalPayload) -> int:
    return (
        len(payload.l1_events)
        + len(payload.l2_entity_cards)
        + len(payload.l2_relationships)
        + len(payload.l2_assertions)
        + len(payload.l2_episodes)
        + len(payload.l2_state_facts)
        + len(payload.l2_state_history)
        + len(payload.l3_reflections)
        + len(payload.l4_procedures)
    )


def rule_backstop_reason(
    *,
    query: str,
    payload: RetrievalPayload,
    decision_source: str,
) -> str | None:
    if decision_source != "llm":
        return None
    if count_payload_results(payload) == 0:
        return "empty_primary"

    actionable_count = (
        len(payload.l1_events)
        + len(payload.l2_relationships)
        + len(payload.l2_assertions)
        + len(payload.l3_reflections)
        + len(payload.l4_procedures)
    )
    if actionable_count == 0:
        return "l2_entity_card_only"
    if not payload.l1_events:
        return "l1_empty_with_l2_data"

    coverage_spans = extract_quoted_spans(query)
    missing_reason = "missing_quoted_coverage"
    if not coverage_spans:
        coverage_spans = extract_comparison_spans(query)
        missing_reason = "missing_comparison_coverage"
    if not coverage_spans:
        return None

    normalized_events = [
        {
            "event_id": str(event.get("event_id") or ""),
            "content": " ".join(extract_query_tokens(str(event.get("content") or ""))),
            "raw_content": str(event.get("content") or ""),
        }
        for event in payload.l1_events
    ]
    if not normalized_events:
        return missing_reason

    span_matches = {
        span: {
            event["event_id"] or f"idx:{index}"
            for index, event in enumerate(normalized_events)
            if span in event["content"]
        }
        for span in coverage_spans
    }
    if any(not matched_event_ids for matched_event_ids in span_matches.values()):
        return missing_reason
    if missing_reason == "missing_comparison_coverage":
        anchored_span_matches = {
            span: {
                event["event_id"] or f"idx:{index}"
                for index, event in enumerate(normalized_events)
                if span in event["content"] and has_temporal_anchor(event["raw_content"])
            }
            for span in coverage_spans
        }
        if any(not matched_event_ids for matched_event_ids in anchored_span_matches.values()):
            return missing_reason
        distinct_match_count = len(
            {event_id for matched_event_ids in anchored_span_matches.values() for event_id in matched_event_ids}
        )
        if distinct_match_count < len(coverage_spans):
            return missing_reason
    return None


def comparison_backstop_queries(
    *,
    query: str,
    payload: RetrievalPayload,
    decision_source: str,
) -> list[str]:
    comparison_spans = extract_comparison_spans(query)
    if not comparison_spans:
        comparison_spans = extract_quoted_spans(query)
    if not comparison_spans:
        return []
    if count_payload_results(payload) > 0:
        backstop_reason = rule_backstop_reason(
            query=query,
            payload=payload,
            decision_source=decision_source,
        )
        if backstop_reason not in ("missing_comparison_coverage", "missing_quoted_coverage"):
            return []

    temporal_tokens = [
        token
        for token in extract_query_tokens(query)
        if token in {
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        }
    ]
    temporal_suffix = " ".join(dict.fromkeys(temporal_tokens))
    queries: list[str] = []
    for span in comparison_spans:
        candidate_query = " ".join(part for part in (span, temporal_suffix) if part).strip()
        if candidate_query and candidate_query not in queries:
            queries.append(candidate_query)
    return queries


def bundle_neighbor_window(_query: str) -> int:
    return 5


def hit_score(hit: dict[str, Any]) -> float:
    for key in ("reranker_score", "retrieval_score"):
        val = hit.get(key)
        if val is not None:
            return float(val)
    trace = hit.get("retrieval_trace")
    if isinstance(trace, dict):
        val = trace.get("base_rrf_score")
        if val is not None:
            return float(val)
    return 0.0


def parse_turn_number(turn_id: str) -> int | None:
    match = _TURN_NUMBER_RE.search(str(turn_id or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None
