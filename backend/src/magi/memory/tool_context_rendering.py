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
    sections = [
        section
        for section in (
            _render_timeline_summary(_items(compact_results, "l1_timeline_summary")),
            _render_l1_events(_items(compact_results, "l1_events")),
            _render_entity_cards(_items(compact_results, "l2_entity_cards")),
            _render_relationships(_items(compact_results, "l2_relationships")),
            _render_assertions(_items(compact_results, "l2_assertions")),
            _render_experiences(_items(compact_results, "l2_experiences")),
            _render_reflections(_items(compact_results, "l3_reflections")),
            _render_procedures(_items(compact_results, "l4_procedures")),
        )
        if section
    ]

    if not sections:
        return "(no memory context)"
    return "\n\n".join(sections)


def _items(compact_results: Dict[str, Any], key: str) -> list[Any]:
    return list(compact_results.get(key) or [])


def _render_section(title: str, rows: list[str]) -> str | None:
    if not rows:
        return None
    return "\n".join([title, *rows])


def _render_timeline_summary(items: list[Any]) -> str | None:
    rows = [
        "- "
        f"session={item.get('session_id')} turn={item.get('turn_id')} "
        f"role={item.get('author_type')} t={item.get('timestamp')}: "
        f"{item.get('summary_preview')}"
        for item in items
    ]
    return _render_section("Timeline Summary:", rows)


def _render_l1_events(items: list[Any]) -> str | None:
    rows = [
        "- "
        f"session={item.get('session_id')} turn={item.get('turn_id')} "
        f"role={item.get('author_type')} score={item.get('score')}: "
        f"{item.get('content_preview')}"
        for item in items
    ]
    return _render_section("Key Events:", rows)


def _render_entity_cards(items: list[Any]) -> str | None:
    rows = [
        "- "
        f"{coalesce_text(item.get('name'), item.get('entity_id'), 'unknown')} "
        f"({coalesce_text(item.get('entity_type'), 'unknown')}): "
        f"{item.get('summary_preview')}"
        for item in items
    ]
    return _render_section("Entity Cards:", rows)


def _render_relationships(items: list[Any]) -> str | None:
    rows = []
    for item in items:
        subject = coalesce_text(item.get("subject"), "unknown")
        predicate = coalesce_text(item.get("predicate"), "RELATED_TO")
        object_value = coalesce_text(item.get("object"), "unknown")
        line = f"- {subject} {predicate} {object_value} (confidence={item.get('confidence')})"
        evidence = coalesce_text(item.get("evidence"))
        if evidence:
            line += f" [{evidence}]"
        rows.append(line)
    return _render_section("Relationships:", rows)


def _render_assertions(items: list[Any]) -> str | None:
    rows = []
    for item in items:
        subject = coalesce_text(item.get("subject"), "unknown")
        predicate = coalesce_text(item.get("predicate"), "assertion")
        claim_preview = coalesce_text(item.get("claim_preview"))
        if item.get("target_entity_id"):
            claim_preview = coalesce_text(claim_preview, item.get("target_entity_id"))
        rows.append(
            "- " f"{subject} {predicate}: {claim_preview} " f"(confidence={item.get('confidence')})"
        )
    return _render_section("Assertions:", rows)


def _render_experiences(items: list[Any]) -> str | None:
    rows = []
    for item in items:
        title = coalesce_text(item.get("user_label"), item.get("title"), "untitled")
        interpretation = coalesce_text(item.get("magi_interpretation"), item.get("user_note"))
        line = f"- {title}"
        if interpretation:
            line += f": {interpretation}"
        source_event_count = item.get("source_event_count")
        if source_event_count is not None:
            line += f" (events={source_event_count})"
        rows.append(line)
    return _render_section("Experiences:", rows)


def _render_reflections(items: list[Any]) -> str | None:
    rows = [
        "- "
        f"{item.get('summary_type')}/{item.get('summary_category')}: "
        f"{item.get('summary_preview')}"
        for item in items
    ]
    return _render_section("Reflections:", rows)


def _render_procedures(items: list[Any]) -> str | None:
    rows = []
    for item in items:
        header = _render_procedure_header(item)
        preview = item.get("description_preview") or ""
        if preview:
            rows.append(f"- {header}: {preview}")
        else:
            rows.append(f"- {header}")
    return _render_section("Execution Experience:", rows)


def _render_procedure_header(item: Any) -> str:
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
    return header


__all__ = ["compact_trace_meta", "render_memory_context"]
