"""Prompt constants for L3 thematic topic summary generation."""

from __future__ import annotations

TOPIC_SUMMARY_SYSTEM_PROMPT = """You generate thematic memory summaries for a local-first agent.

Rules:
- Use only the supplied evidence pack.
- Summarize what repeatedly surfaced around the topic and why it matters.
- Treat rule_hints as guidance, not as independent evidence.
- Do not invent entity ids, event ids, or unsupported preferences.
- Return a JSON object with: content, key_topics, key_entities, importance_aggregate.
"""

TOPIC_SUMMARY_OUTPUT_SCHEMA = {
    "content": "A concise thematic recap grounded in the evidence pack.",
    "key_topics": ["short_topic_label"],
    "key_entities": [{"entity_id": "optional_entity_id", "entity_type": "optional_entity_type"}],
    "importance_aggregate": 0.0,
}


__all__ = ["TOPIC_SUMMARY_OUTPUT_SCHEMA", "TOPIC_SUMMARY_SYSTEM_PROMPT"]
