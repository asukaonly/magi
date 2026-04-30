"""Per-layer compaction helpers for memory tool context."""

from __future__ import annotations

import json
from typing import Any

from .tool_context_common import coalesce_text, truncate_text


def compact_workbench_items(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        preview, truncated = truncate_text(item.get("content") or item.get("summary"), max_text_chars=max_text_chars)
        compact.append(
            {
                "type": item.get("type"),
                "title": item.get("title"),
                "content_preview": preview,
                "content_truncated": truncated,
            }
        )
    return compact


def compact_l1_events(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        preview, truncated = truncate_text(item.get("content"), max_text_chars=max_text_chars)
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


def compact_timeline_summary(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        preview, truncated = truncate_text(item.get("summary"), max_text_chars=max_text_chars)
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


def compact_evidence_bundles(items: Any, *, max_items: int) -> list[dict[str, Any]]:
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


def compact_entity_cards(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        preview, truncated = truncate_text(
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


def compact_relationships(items: Any, *, max_items: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {
            "subject": coalesce_text(item.get("subject"), item.get("subject_id")),
            "subject_type": item.get("subject_type"),
            "predicate": item.get("predicate"),
            "object": coalesce_text(item.get("object"), item.get("object_id")),
            "object_type": item.get("object_type"),
            "confidence": item.get("confidence"),
        }
        evidence = coalesce_text(item.get("evidence_text"), item.get("natural_summary"))
        if evidence:
            entry["evidence"] = evidence
        compact.append(entry)
    return compact


def compact_assertions(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        assertion_text = coalesce_text(
            item.get("claim"),
            item.get("content"),
            item.get("trait_value"),
            item.get("target_entity_id"),
        )
        preview, truncated = truncate_text(
            assertion_text,
            max_text_chars=max_text_chars,
        )
        compact.append(
            {
                "subject": coalesce_text(item.get("subject"), item.get("entity_id")),
                "predicate": coalesce_text(item.get("predicate"), item.get("trait_name"), item.get("trait_family")),
                "claim_preview": preview,
                "claim_truncated": truncated,
                "target_entity_id": coalesce_text(item.get("target_entity_id")),
                "confidence": item.get("confidence") or item.get("confidence_score"),
            }
        )
    return compact


def compact_reflections(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        preview, truncated = truncate_text(
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


def compact_procedures(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        strategy_hint = extract_procedure_hint(item.get("optimized_prompt"))
        preview, truncated = truncate_text(
            strategy_hint or item.get("description") or item.get("summary"),
            max_text_chars=max_text_chars,
        )
        entry: dict[str, Any] = {
            "skill_id": item.get("skill_id"),
            "skill_name": item.get("skill_name"),
            "skill_category": item.get("skill_category"),
            "description_preview": preview,
            "description_truncated": truncated,
            "success_rate": item.get("success_rate"),
            "total_attempts": item.get("total_attempts"),
        }
        breaker = item.get("circuit_breaker_state")
        if breaker and breaker != "closed":
            entry["breaker_state"] = breaker
        compact.append(entry)
    return compact


def extract_procedure_hint(optimized_prompt: Any) -> str | None:
    """Try to pull a strategy hint from the optimized_prompt field."""
    if not optimized_prompt:
        return None
    text = str(optimized_prompt).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            approach = str(data.get("recommended_approach") or "").strip()
            if approach:
                return approach
            cases = data.get("best_use_cases") or []
            if cases:
                return str(cases[0]).strip()
            return None
    except (json.JSONDecodeError, TypeError):
        pass
    return None


__all__ = [
    "compact_assertions",
    "compact_entity_cards",
    "compact_evidence_bundles",
    "compact_l1_events",
    "compact_procedures",
    "compact_reflections",
    "compact_relationships",
    "compact_timeline_summary",
    "compact_workbench_items",
    "extract_procedure_hint",
]
