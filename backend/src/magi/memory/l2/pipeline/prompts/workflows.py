"""Prompt templates for auxiliary L2 workflow LLM calls."""

from __future__ import annotations

import json

from ...models import (
    L2BatchEntityResolutionItem,
    L2EntityCandidate,
    L2EntityResolutionMention,
)


ENTITY_RESOLUTION_SYSTEM_PROMPT = """You are an entity resolution engine for a memory graph.

Your job is to determine whether a mention refers to one of the provided candidate entities.
Be conservative:
- Prefer unresolved over guessing.
- Use local context, aliases, semantics, and common nicknames.
- Do not create a new fact beyond identity resolution.
- Return JSON only.
"""

BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT = """You are an entity resolution engine for a memory graph.

Your job is to determine, for EACH mention in the batch, whether it refers to one of its provided candidate entities.
Be conservative:
- Prefer unresolved over guessing.
- Use local context, aliases, semantics, and common nicknames.
- Do not create a new fact beyond identity resolution.
- Return JSON only.
"""


def render_entity_resolution_prompt(
    *,
    mention: L2EntityResolutionMention,
    candidate_entities: list[L2EntityCandidate],
) -> str:
    return (
        "Resolve the entity mention to one of the candidate canonical entities if possible.\n\n"
        f"Mention:\n{json.dumps(mention.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        f"Candidate entities:\n{json.dumps([item.to_dict() for item in candidate_entities], ensure_ascii=False, indent=2)}\n\n"
        "Return JSON with this schema:\n"
        '{\n  "resolution": {\n    "decision": "match|unresolved|create_new_candidate",\n    "matched_entity_id": "string or null",\n'
        '    "matched_entity_name": "string or null",\n    "confidence": 0.0,\n    "reason_tags": ["string"],\n'
        '    "should_merge": true,\n    "canonical_name_suggestion": "string or null"\n  }\n}'
    )


def render_batch_entity_resolution_prompt(
    *,
    items: list[L2BatchEntityResolutionItem],
) -> str:
    items_payload = [item.to_dict() for item in items]
    return (
        "Resolve each entity mention to one of its candidate canonical entities if possible.\n\n"
        f"Mentions to resolve:\n{json.dumps(items_payload, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON with this schema:\n"
        '{\n  "resolutions": [\n    {\n      "mention_key": "string (echo back the mention_key)",\n'
        '      "decision": "match|unresolved|create_new_candidate",\n      "matched_entity_id": "string or null",\n'
        '      "matched_entity_name": "string or null",\n      "confidence": 0.0,\n      "reason_tags": ["string"],\n'
        '      "should_merge": true,\n      "canonical_name_suggestion": "string or null"\n    }\n  ]\n}'
    )


__all__ = [
    "BATCH_ENTITY_RESOLUTION_SYSTEM_PROMPT",
    "ENTITY_RESOLUTION_SYSTEM_PROMPT",
    "render_batch_entity_resolution_prompt",
    "render_entity_resolution_prompt",
]
