"""Context-formatting helpers for memory tool results."""

from __future__ import annotations

from typing import Any, Dict


def compact_memory_tool_data(
    data: Dict[str, Any],
    *,
    max_items: int,
    max_text_chars: int,
) -> Dict[str, Any]:
    """Compress memory_query tool results for LLM tool-message context."""
    if not isinstance(data, dict):
        return data

    results = data.get("results")
    if not isinstance(results, dict):
        return data

    compact_results: Dict[str, Any] = {}

    if "l0_workbench" in results:
        compact_results["l0_workbench"] = _compact_workbench_items(
            results.get("l0_workbench"), max_items=max_items, max_text_chars=max_text_chars
        )
    if "l1_events" in results:
        compact_results["l1_events"] = _compact_l1_events(
            results.get("l1_events"), max_items=max_items, max_text_chars=max_text_chars
        )
    if "l1_timeline_summary" in results:
        compact_results["l1_timeline_summary"] = _compact_timeline_summary(
            results.get("l1_timeline_summary"), max_items=max_items, max_text_chars=max_text_chars
        )
    if "l1_evidence_bundles" in results:
        compact_results["l1_evidence_bundles"] = _compact_evidence_bundles(
            results.get("l1_evidence_bundles"), max_items=max_items
        )
    if "l2_entity_cards" in results:
        compact_results["l2_entity_cards"] = _compact_entity_cards(
            results.get("l2_entity_cards"), max_items=max_items, max_text_chars=max_text_chars
        )
    if "l2_relationships" in results:
        compact_results["l2_relationships"] = _compact_relationships(
            results.get("l2_relationships"), max_items=max_items
        )
    if "l2_assertions" in results:
        compact_results["l2_assertions"] = _compact_assertions(
            results.get("l2_assertions"), max_items=max_items, max_text_chars=max_text_chars
        )
    if "l3_reflections" in results:
        compact_results["l3_reflections"] = _compact_reflections(
            results.get("l3_reflections"), max_items=max_items, max_text_chars=max_text_chars
        )
    if "l4_procedures" in results:
        compact_results["l4_procedures"] = _compact_procedures(
            results.get("l4_procedures"), max_items=max_items, max_text_chars=max_text_chars
        )

    compact_meta = _compact_trace_meta(data.get("meta") or results.get("trace"))

    compact_payload: Dict[str, Any] = {
        "results": compact_results,
        "meta": compact_meta,
    }
    if "agent_id" in data:
        compact_payload["agent_id"] = data.get("agent_id")
    return compact_payload


def _truncate_text(text: Any, *, max_text_chars: int) -> tuple[str, bool]:
    normalized = str(text or "")
    return normalized[:max_text_chars], len(normalized) > max_text_chars


def _compact_workbench_items(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        preview, truncated = _truncate_text(item.get("content") or item.get("summary"), max_text_chars=max_text_chars)
        compact.append(
            {
                "type": item.get("type"),
                "title": item.get("title"),
                "content_preview": preview,
                "content_truncated": truncated,
            }
        )
    return compact


def _compact_l1_events(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        preview, truncated = _truncate_text(item.get("content"), max_text_chars=max_text_chars)
        compact.append(
            {
                "session_id": item.get("session_id"),
                "turn_id": item.get("turn_id"),
                "timestamp": item.get("timestamp"),
                "author_type": item.get("author_type"),
                "event_type": item.get("event_type"),
                "score": item.get("score"),
                "content_preview": preview,
                "content_truncated": truncated,
            }
        )
    return compact


def _compact_timeline_summary(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        preview, truncated = _truncate_text(item.get("summary"), max_text_chars=max_text_chars)
        compact.append(
            {
                "session_id": item.get("session_id"),
                "turn_id": item.get("turn_id"),
                "timestamp": item.get("timestamp"),
                "author_type": item.get("author_type"),
                "summary_preview": preview,
                "summary_truncated": truncated,
            }
        )
    return compact


def _compact_evidence_bundles(items: Any, *, max_items: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "session_id": item.get("session_id"),
                "hit_turn_ids": list(item.get("hit_turn_ids") or [])[:max_items],
                "hit_event_ids": list(item.get("hit_event_ids") or [])[:max_items],
                "event_count": len(item.get("events") or []),
            }
        )
    return compact


def _compact_entity_cards(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        preview, truncated = _truncate_text(
            item.get("summary") or item.get("description"),
            max_text_chars=max_text_chars,
        )
        compact.append(
            {
                "entity_id": item.get("entity_id"),
                "name": item.get("name"),
                "entity_type": item.get("entity_type"),
                "summary_preview": preview,
                "summary_truncated": truncated,
            }
        )
    return compact


def _compact_relationships(items: Any, *, max_items: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "subject": item.get("subject"),
                "predicate": item.get("predicate"),
                "object": item.get("object"),
                "confidence": item.get("confidence"),
            }
        )
    return compact


def _compact_assertions(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        preview, truncated = _truncate_text(
            item.get("claim") or item.get("content"),
            max_text_chars=max_text_chars,
        )
        compact.append(
            {
                "subject": item.get("subject"),
                "predicate": item.get("predicate"),
                "claim_preview": preview,
                "claim_truncated": truncated,
                "confidence": item.get("confidence"),
            }
        )
    return compact


def _compact_reflections(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        preview, truncated = _truncate_text(
            item.get("summary") or item.get("content"),
            max_text_chars=max_text_chars,
        )
        compact.append(
            {
                "summary_type": item.get("summary_type"),
                "summary_category": item.get("summary_category"),
                "summary_preview": preview,
                "summary_truncated": truncated,
            }
        )
    return compact


def _compact_procedures(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        preview, truncated = _truncate_text(
            item.get("description") or item.get("summary"),
            max_text_chars=max_text_chars,
        )
        compact.append(
            {
                "skill_id": item.get("skill_id"),
                "skill_name": item.get("skill_name"),
                "skill_category": item.get("skill_category"),
                "description_preview": preview,
                "description_truncated": truncated,
                "success_rate": item.get("success_rate"),
            }
        )
    return compact


def _compact_trace_meta(trace: Any) -> dict[str, Any]:
    if not isinstance(trace, dict):
        return {}
    allowed_keys = (
        "intent_source",
        "intent_reasoning",
        "query_mode",
        "primary_count",
        "l1_hit_count",
        "l1_evidence_bundle_count",
        "l1_timeline_summary_count",
        "rule_backstop_triggered",
        "rule_backstop_reason",
        "comparison_backstop_triggered",
        "temporal_distance_backstop_triggered",
    )
    return {key: trace.get(key) for key in allowed_keys if key in trace}
