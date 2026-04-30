"""Prompt constants for L3 temporal summary generation."""

from __future__ import annotations

TEMPORAL_SUMMARY_SYSTEM_PROMPT = """You generate temporal memory summaries for a local-first agent.

Rules:
- Use only the supplied evidence pack.
- Compress repetition and surface concrete changes, priorities, and recurring patterns.
- Do not invent entity ids, event ids, preferences, or psychological diagnoses.
- Return a JSON object with: content, key_topics, key_entities, sentiment_summary, change_and_pattern, importance_aggregate.
- If evidence is weak, stay conservative and summarize only explicit content.
"""

TEMPORAL_SUMMARY_OUTPUT_SCHEMA = {
    "content": "A concise temporal recap grounded in the evidence pack.",
    "key_topics": ["short_topic_label"],
    "key_entities": [{"entity_id": "optional_entity_id", "entity_type": "optional_entity_type"}],
    "sentiment_summary": {"tone": "optional_tone", "stress_level": 0.0},
    "change_and_pattern": {
        "changes": ["explicit shift observed in the window"],
        "patterns": ["recurring behavior or constraint grounded in evidence"],
    },
    "importance_aggregate": 0.0,
}


__all__ = ["TEMPORAL_SUMMARY_OUTPUT_SCHEMA", "TEMPORAL_SUMMARY_SYSTEM_PROMPT"]
