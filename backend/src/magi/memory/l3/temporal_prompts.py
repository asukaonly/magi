"""Prompt constants for L3 temporal summary generation."""

from __future__ import annotations

TEMPORAL_SUMMARY_SYSTEM_PROMPT = """You generate temporal memory summaries for a local-first agent.

Rules:
- Use only the supplied evidence pack.
- Compress repetition while preserving retrieval-useful anchors: named projects, tools, services, domains, media titles, decisions, unresolved threads, and representative source-specific behavior.
- Do not collapse day, week, or month windows into one generic theme; keep enough structure for later recall and comparison.
- Surface concrete changes, priorities, decisions, open threads, and recurring patterns.
- Do not invent entity ids, event ids, preferences, or psychological diagnoses.
- The `content` field is user-facing Markdown (GitHub-flavored). Use short paragraphs and only the section headings or bullets that help the user understand the period; no top-level `#` heading. Keep it compact and avoid turning structure into a report template.
- The `essence_prose` field is a short card preview for product surfaces. It should be 1-2 natural sentences that help the user quickly understand the period without opening details.
- The `change_and_pattern` JSON object holds machine-indexed structured anchors and intentionally overlaps with `content`; both must stay evidence-grounded and consistent with each other.
- For week and month windows, when previous_period_summaries contains 2 or more entries, treat them as an ordered series and identify whether each rising or falling theme is a sustained multi-period trajectory or a single-period spike. Mark sustained trajectories explicitly in change_and_pattern.trend_shifts.
- For week and month windows, when child_period_summaries are present, treat them as the primary skeleton: synthesize from child headlines, decisions, and open threads rather than re-reading every raw event.
- Return a JSON object with: content, essence_prose, key_topics, key_entities, sentiment_summary, change_and_pattern, importance_aggregate.
- If evidence is weak, stay conservative and summarize only explicit content.
"""

TEMPORAL_SUMMARY_OUTPUT_SCHEMA = {
    "content": "Markdown recap. Use the section headings listed in the period Structure Contract (no top-level `#`). Sections may be omitted when no evidence supports them. Section bodies should be a short paragraph or a tight bullet list, not long prose.",
    "essence_prose": "Short card preview for product surfaces. 1-2 natural user-facing sentences, around 40-120 Chinese characters when the target language is Chinese. It must summarize the period, not list every section.",
    "key_topics": ["short_topic_label"],
    "key_entities": [{"entity_id": "optional_entity_id", "entity_type": "optional_entity_type"}],
    "sentiment_summary": {"tone": "optional_tone", "stress_level": 0.0},
    "change_and_pattern": {
        "headline": "single short sentence hook used as retrieval preview; mirrors the `## 要点` section in content.",
        "timeline": ["ordered phase, activity block, or stage shift with concrete anchors"],
        "daily_breakdown": ["MM-DD: one-line per-day headline (week summaries only)"],
        "weekly_breakdown": ["Week N (MM-DD~MM-DD): one-line per-week headline (month summaries only)"],
        "source_signals": ["source-specific behavior signal grounded in evidence"],
        "decisions_and_actions": ["explicit decision, action, task, purchase, or commitment"],
        "changes": ["explicit shift observed in the window"],
        "patterns": ["recurring behavior or constraint grounded in evidence"],
        "open_threads": ["follow-up, unresolved thread, or continuing interest grounded in evidence"],
        "trend_shifts": {
            "rising": ["theme gaining attention vs previous periods"],
            "falling": ["theme losing attention vs previous periods"],
            "new": ["theme that did not appear in previous periods"],
            "persisting": ["theme stable across periods"],
        },
        "metrics": {
            "event_count": 0,
            "covered_children": 0,
            "deep_work_blocks": 0,
            "fragmentation_score": 0.0,
            "topic_switch_count": 0,
            "dominant_sources": ["source_id"],
        },
    },
    "importance_aggregate": 0.0,
}


__all__ = ["TEMPORAL_SUMMARY_OUTPUT_SCHEMA", "TEMPORAL_SUMMARY_SYSTEM_PROMPT"]
