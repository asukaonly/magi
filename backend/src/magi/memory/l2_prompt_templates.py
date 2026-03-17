"""Prompt templates for L2 extraction and reconcile helpers."""

from __future__ import annotations

import json
from typing import Any


ENTITY_MENTION_SYSTEM_PROMPT = """You are an information extraction engine for a memory system.

Your task is to extract entity mentions from the given text.
You must be conservative:
- Do not invent entities.
- If a phrase is ambiguous and cannot be grounded from the text, skip it.
- Extract only entities that are explicitly referenced or strongly implied by the local context.
- Return JSON only.
- Do not include any explanation.
"""

ENTITY_RESOLUTION_SYSTEM_PROMPT = """You are an entity resolution engine for a memory graph.

Your job is to determine whether a mention refers to one of the provided candidate entities.
Be conservative:
- Prefer unresolved over guessing.
- Use local context, aliases, semantics, and common nicknames.
- Do not create a new fact beyond identity resolution.
- Return JSON only.
"""

TOM_EXTRACTION_SYSTEM_PROMPT = """You are a defensive theory-of-mind extraction engine.

Your task is to extract low-confidence, evidence-bound inference candidates about temporary states, preferences, triggers, or relationship changes.
Be cautious:
- Do not diagnose mental illness.
- Do not produce strong personality judgments from a single event.
- Single-event inferences must remain tentative and low-confidence.
- Return JSON only.
"""


def render_entity_mention_prompt(*, event_text: str, context_texts: list[str]) -> str:
    payload = {
        "event_text": event_text,
        "context_texts": context_texts,
        "output_schema": {
            "mentions": [
                {
                    "mention_text": "string",
                    "normalized_surface": "string",
                    "entity_type": "string",
                    "canonical_name_hint": "string or null",
                    "alias_signals": ["string"],
                    "evidence_text": "string",
                    "confidence": 0.0,
                }
            ]
        },
    }
    return f"Extract entity mentions from the following memory event.\n\nEvent text:\n{event_text}\n\nContext:\n{json.dumps(context_texts, ensure_ascii=False)}\n\nReturn JSON using this contract:\n{json.dumps(payload['output_schema'], ensure_ascii=False, indent=2)}"


def render_entity_resolution_prompt(*, mention: dict[str, Any], candidate_entities: list[dict[str, Any]]) -> str:
    return (
        "Resolve the entity mention to one of the candidate canonical entities if possible.\n\n"
        f"Mention:\n{json.dumps(mention, ensure_ascii=False, indent=2)}\n\n"
        f"Candidate entities:\n{json.dumps(candidate_entities, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON with this schema:\n"
        '{\n  "resolution": {\n    "decision": "match|unresolved|create_new_candidate",\n    "matched_entity_id": "string or null",\n'
        '    "matched_entity_name": "string or null",\n    "confidence": 0.0,\n    "reason_tags": ["string"],\n'
        '    "should_merge": true,\n    "canonical_name_suggestion": "string or null"\n  }\n}'
    )


def render_tom_extraction_prompt(*, event_window: dict[str, Any], focal_entities: list[dict[str, Any]]) -> str:
    return (
        "Extract tentative ToM assertion candidates from the following memory event window.\n\n"
        f"Event window:\n{json.dumps(event_window, ensure_ascii=False, indent=2)}\n\n"
        f"Focal entities:\n{json.dumps(focal_entities, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON with this schema:\n"
        '{\n  "assertion_candidates": [\n    {\n      "entity_ref": "string",\n      "entity_type": "string",\n'
        '      "trait_family": "string",\n      "trait_name": "string",\n      "trait_value": "string or JSON string",\n'
        '      "inference_depth": "topology_only|defensive_psychology",\n      "volatility_index": 0.0,\n'
        '      "confidence": 0.0,\n      "validation_state": "tentative",\n      "evidence_texts": ["string"],\n'
        '      "supporting_event_ids": ["string"],\n      "notes": "string or null"\n    }\n  ]\n}'
    )


__all__ = [
    "ENTITY_MENTION_SYSTEM_PROMPT",
    "ENTITY_RESOLUTION_SYSTEM_PROMPT",
    "TOM_EXTRACTION_SYSTEM_PROMPT",
    "render_entity_mention_prompt",
    "render_entity_resolution_prompt",
    "render_tom_extraction_prompt",
]
