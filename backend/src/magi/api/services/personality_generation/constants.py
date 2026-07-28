"""Constants shared by the personality generation service."""

from __future__ import annotations

from typing import Any


REQUIRED_REGISTERS = ("chat", "analysis", "task", "emotional", "crisis")
PERSONALITY_GENERATION_MAX_CONCURRENT_LLM_CALLS = 6
PERSONALITY_GENERATION_JOB_TTL_SECONDS = 30 * 60

JSON_DIAGNOSTIC_CONTRACT_CHARS = 2400
JSON_DIAGNOSTIC_OUTPUT_CHARS = 1600
JSON_DIAGNOSTIC_LINE_CONTEXT = 2

META_DESIGN_KEY = "_meta_design"
META_DESIGN_FIELDS = ("core_theme", "failure_mode", "key_constraint")
GENERATION_INTERNAL_KEYS = frozenset({META_DESIGN_KEY})
FIXED_SURFACE_LAYER: dict[str, Any] = {
    "layer_id": "surface",
    "unlock_condition": None,
    "modifiers": {},
}

GENERATION_STAGE_DEFINITIONS = (
    {"stage_id": "reference", "label": "Verify reference material"},
    {"stage_id": "base", "label": "Understand persona spine"},
    {"stage_id": "registers", "label": "Design conversation registers"},
    {"stage_id": "rules", "label": "Design triggers and quiet hours"},
    {"stage_id": "layers", "label": "Design deep persona layers"},
    {"stage_id": "bootstrap", "label": "Write examples and first contact"},
    {"stage_id": "appearance", "label": "Draft portrait prompt"},
    {"stage_id": "integrate", "label": "Integrate and validate"},
)
