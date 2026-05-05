"""Prompt constants for L3 temporal summary generation."""

from __future__ import annotations

TEMPORAL_SUMMARY_SYSTEM_PROMPT = """You generate temporal memory summaries for a local-first agent.

Rules:
- Use only the supplied evidence pack.
- Compress repetition while preserving retrieval-useful anchors: named projects, tools, services, domains, media titles, decisions, unresolved threads, and representative source-specific behavior.
- Do not collapse day, week, or month windows into one generic theme; keep enough structure for later recall and comparison.
- Surface concrete changes, priorities, decisions, open threads, and recurring patterns.
- Do not invent entity ids, event ids, preferences, or psychological diagnoses.
- Return a JSON object with: content, key_topics, key_entities, sentiment_summary, change_and_pattern, importance_aggregate.
- If evidence is weak, stay conservative and summarize only explicit content.
"""

TEMPORAL_SUMMARY_OUTPUT_SCHEMA = {
    "content": "A structured temporal recap grounded in the evidence pack, with period-appropriate concrete anchors.",
    "key_topics": ["short_topic_label"],
    "key_entities": [{"entity_id": "optional_entity_id", "entity_type": "optional_entity_type"}],
    "sentiment_summary": {"tone": "optional_tone", "stress_level": 0.0},
    "change_and_pattern": {
        "timeline": ["ordered phase, activity block, or stage shift with concrete anchors"],
        "source_signals": ["source-specific behavior signal grounded in evidence"],
        "decisions_and_actions": ["explicit decision, action, task, purchase, or commitment"],
        "changes": ["explicit shift observed in the window"],
        "patterns": ["recurring behavior or constraint grounded in evidence"],
        "open_threads": ["follow-up, unresolved thread, or continuing interest grounded in evidence"],
    },
    "importance_aggregate": 0.0,
}


__all__ = ["TEMPORAL_SUMMARY_OUTPUT_SCHEMA", "TEMPORAL_SUMMARY_SYSTEM_PROMPT"]
