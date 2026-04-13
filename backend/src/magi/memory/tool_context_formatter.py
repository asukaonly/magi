"""Context-formatting helpers for memory tool results."""

from __future__ import annotations

import json
from typing import Any, Dict


def _coalesce_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return ""


def compact_memory_tool_data(
    data: Dict[str, Any],
    *,
    max_items: int,
    max_text_chars: int,
) -> Dict[str, Any]:
    """Compress memory_query tool results for LLM tool-message context."""
    if not isinstance(data, dict):
        return data

    historical_recall = data.get("historical_recall")
    if isinstance(historical_recall, dict):
        return {
            "historical_recall": historical_recall,
        }

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

    merged_trace: dict[str, Any] = {}
    if isinstance(results.get("trace"), dict):
        merged_trace.update(results.get("trace") or {})
    if isinstance(data.get("meta"), dict):
        merged_trace.update(data.get("meta") or {})
    compact_meta = _compact_trace_meta(merged_trace)

    compact_payload: Dict[str, Any] = {
        "memory_context": _render_memory_context(compact_results),
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
        entry: dict[str, Any] = {
            "subject": _coalesce_text(item.get("subject"), item.get("subject_id")),
            "subject_type": item.get("subject_type"),
            "predicate": item.get("predicate"),
            "object": _coalesce_text(item.get("object"), item.get("object_id")),
            "object_type": item.get("object_type"),
            "confidence": item.get("confidence"),
        }
        evidence = _coalesce_text(item.get("evidence_text"), item.get("natural_summary"))
        if evidence:
            entry["evidence"] = evidence
        compact.append(entry)
    return compact


def _compact_assertions(items: Any, *, max_items: int, max_text_chars: int) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        assertion_text = _coalesce_text(
            item.get("claim"),
            item.get("content"),
            item.get("trait_value"),
            item.get("target_entity_id"),
        )
        preview, truncated = _truncate_text(
            assertion_text,
            max_text_chars=max_text_chars,
        )
        compact.append(
            {
                "subject": _coalesce_text(item.get("subject"), item.get("entity_id")),
                "predicate": _coalesce_text(item.get("predicate"), item.get("trait_name"), item.get("trait_family")),
                "claim_preview": preview,
                "claim_truncated": truncated,
                "target_entity_id": _coalesce_text(item.get("target_entity_id")),
                "confidence": item.get("confidence") or item.get("confidence_score"),
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
        strategy_hint = _extract_procedure_hint(item.get("optimized_prompt"))
        preview, truncated = _truncate_text(
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


def _extract_procedure_hint(optimized_prompt: Any) -> str | None:
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
        "l2_entity_card_count",
        "l2_relationship_count",
        "l2_assertion_count",
        "l2_query_trace",
        "rule_backstop_triggered",
        "rule_backstop_reason",
        "comparison_backstop_triggered",
    )
    return {key: trace.get(key) for key in allowed_keys if key in trace}


def _render_memory_context(compact_results: Dict[str, Any]) -> str:
    sections: list[str] = []

    timeline_items = list(compact_results.get("l1_timeline_summary") or [])
    if timeline_items:
        lines = ["Timeline Summary:"]
        for item in timeline_items:
            lines.append(
                "- "
                f"session={item.get('session_id')} turn={item.get('turn_id')} "
                f"role={item.get('author_type')} t={item.get('timestamp')}: "
                f"{item.get('summary_preview')}"
            )
        sections.append("\n".join(lines))

    event_items = list(compact_results.get("l1_events") or [])
    if event_items:
        lines = ["Key Events:"]
        for item in event_items:
            lines.append(
                "- "
                f"session={item.get('session_id')} turn={item.get('turn_id')} "
                f"role={item.get('author_type')} score={item.get('score')}: "
                f"{item.get('content_preview')}"
            )
        sections.append("\n".join(lines))

    entity_cards = list(compact_results.get("l2_entity_cards") or [])
    if entity_cards:
        lines = ["Entity Cards:"]
        for item in entity_cards:
            lines.append(
                "- "
                f"{_coalesce_text(item.get('name'), item.get('entity_id'), 'unknown')} "
                f"({_coalesce_text(item.get('entity_type'), 'unknown')}): "
                f"{item.get('summary_preview')}"
            )
        sections.append("\n".join(lines))

    relationships = list(compact_results.get("l2_relationships") or [])
    if relationships:
        lines = ["Relationships:"]
        for item in relationships:
            subject = _coalesce_text(item.get("subject"), "unknown")
            predicate = _coalesce_text(item.get("predicate"), "RELATED_TO")
            object_value = _coalesce_text(item.get("object"), "unknown")
            line = f"- {subject} {predicate} {object_value} (confidence={item.get('confidence')})"
            evidence = _coalesce_text(item.get("evidence"))
            if evidence:
                line += f" [{evidence}]"
            lines.append(line)
        sections.append("\n".join(lines))

    assertions = list(compact_results.get("l2_assertions") or [])
    if assertions:
        lines = ["Assertions:"]
        for item in assertions:
            subject = _coalesce_text(item.get("subject"), "unknown")
            predicate = _coalesce_text(item.get("predicate"), "assertion")
            claim_preview = _coalesce_text(item.get("claim_preview"))
            if item.get("target_entity_id"):
                claim_preview = _coalesce_text(claim_preview, item.get("target_entity_id"))
            lines.append(
                "- "
                f"{subject} {predicate}: {claim_preview} "
                f"(confidence={item.get('confidence')})"
            )
        sections.append("\n".join(lines))

    reflections = list(compact_results.get("l3_reflections") or [])
    if reflections:
        lines = ["Reflections:"]
        for item in reflections:
            lines.append(
                "- "
                f"{item.get('summary_type')}/{item.get('summary_category')}: "
                f"{item.get('summary_preview')}"
            )
        sections.append("\n".join(lines))

    procedures = list(compact_results.get("l4_procedures") or [])
    if procedures:
        lines = ["Execution Experience:"]
        for item in procedures:
            name = item.get("skill_name") or "unknown"
            category = item.get("skill_category") or "tool"
            rate = item.get("success_rate")
            attempts = item.get("total_attempts")
            header = f"{name} ({category}"
            if rate is not None and attempts:
                header += f", {rate:.0%} success over {attempts} uses"
            header += ")"
            breaker = item.get("breaker_state")
            if breaker == "open":
                header += " [UNAVAILABLE - breaker open]"
            elif breaker == "half_open":
                header += " [recovering]"
            preview = item.get("description_preview") or ""
            if preview:
                lines.append(f"- {header}: {preview}")
            else:
                lines.append(f"- {header}")
        sections.append("\n".join(lines))

    if not sections:
        return "(no memory context)"
    return "\n\n".join(sections)
