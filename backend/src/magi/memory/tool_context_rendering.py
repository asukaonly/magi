"""Render compacted memory tool results into LLM context text."""

from __future__ import annotations

from typing import Any, Dict

from .tool_context_common import coalesce_text


def compact_trace_meta(trace: Any) -> dict[str, Any]:
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
        "l2_experience_count",
        "l2_query_trace",
        "rule_backstop_triggered",
        "rule_backstop_reason",
        "comparison_backstop_triggered",
    )
    return {key: trace.get(key) for key in allowed_keys if key in trace}


def render_memory_context(compact_results: Dict[str, Any]) -> str:
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
                f"{coalesce_text(item.get('name'), item.get('entity_id'), 'unknown')} "
                f"({coalesce_text(item.get('entity_type'), 'unknown')}): "
                f"{item.get('summary_preview')}"
            )
        sections.append("\n".join(lines))

    relationships = list(compact_results.get("l2_relationships") or [])
    if relationships:
        lines = ["Relationships:"]
        for item in relationships:
            subject = coalesce_text(item.get("subject"), "unknown")
            predicate = coalesce_text(item.get("predicate"), "RELATED_TO")
            object_value = coalesce_text(item.get("object"), "unknown")
            line = f"- {subject} {predicate} {object_value} (confidence={item.get('confidence')})"
            evidence = coalesce_text(item.get("evidence"))
            if evidence:
                line += f" [{evidence}]"
            lines.append(line)
        sections.append("\n".join(lines))

    assertions = list(compact_results.get("l2_assertions") or [])
    if assertions:
        lines = ["Assertions:"]
        for item in assertions:
            subject = coalesce_text(item.get("subject"), "unknown")
            predicate = coalesce_text(item.get("predicate"), "assertion")
            claim_preview = coalesce_text(item.get("claim_preview"))
            if item.get("target_entity_id"):
                claim_preview = coalesce_text(claim_preview, item.get("target_entity_id"))
            lines.append(
                "- "
                f"{subject} {predicate}: {claim_preview} "
                f"(confidence={item.get('confidence')})"
            )
        sections.append("\n".join(lines))

    experiences = list(compact_results.get("l2_experiences") or [])
    if experiences:
        lines = ["Experiences:"]
        for item in experiences:
            title = coalesce_text(item.get("user_label"), item.get("title"), "untitled")
            interpretation = coalesce_text(item.get("magi_interpretation"), item.get("user_note"))
            line = f"- {title}"
            if interpretation:
                line += f": {interpretation}"
            source_event_count = item.get("source_event_count")
            if source_event_count is not None:
                line += f" (events={source_event_count})"
            lines.append(line)
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


__all__ = ["compact_trace_meta", "render_memory_context"]
