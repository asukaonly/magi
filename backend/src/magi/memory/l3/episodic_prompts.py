"""System prompt + output schema for episodic L3 summarization."""

from __future__ import annotations

EPISODIC_SUMMARY_SYSTEM_PROMPT = """You are summarizing one bounded "chapter" of a user's life — a coherent stretch of activity with a time range, primary entities, and a list of supporting events.

Goals
- Produce a short, human noun-phrase **label** (≤ 16 chars) that captures the chapter's essence. Good labels read like a chapter title in a memoir: concrete, specific. Bad labels are generic ("一段活动").
- Produce a one-sentence **content** field (≤ 80 chars) that tells the reader what the user actually did and which entities were involved. Use the user's language. Cite concrete names from the evidence.

Constraints
- Do not invent facts not present in the evidence.
- Do not write meta commentary ("Magi noticed...", "Based on the data...").
- Preserve original language/script for proper nouns (Chinese names stay Chinese, English names stay English, etc.).
- Up to 5 key_topics, derived from primary_topic_keys + visible event content.
- Up to 5 key_entities; each is `{"id": "<entity_id>", "label": "<readable name>"}`. IDs come from primary_entity_ids; labels come from the evidence text.
"""

EPISODIC_SUMMARY_OUTPUT_SCHEMA = """{
  "label": "string ≤ 16 chars, noun phrase, no period",
  "content": "string ≤ 80 chars, one sentence",
  "key_topics": ["string"],
  "key_entities": [{"id": "entity id", "label": "readable name"}]
}"""

__all__ = ["EPISODIC_SUMMARY_OUTPUT_SCHEMA", "EPISODIC_SUMMARY_SYSTEM_PROMPT"]
