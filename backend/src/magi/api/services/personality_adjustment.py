"""Scoped LLM adjustments for an unsaved persona draft."""

from __future__ import annotations

import copy
import json
from typing import Any, Callable, Optional

from ...config.models import LLMSettings
from ...llm import create_llm_adapter
from ...llm.draft import resolve_adapter_for_scenario
from ..routers.personality_config_schemas import (
    PersonaGenerationIntentModel,
    PersonalityConfigModel,
)
from .personality_generation.model_stages import _run_generation_stage
from .personality_generation.normalization import (
    _deep_merge_payload,
    normalize_generated_personality_payload,
)

PERSONA_ADJUSTMENT_SYSTEM_PROMPT = """You apply one scoped adjustment to an existing persona configuration.

Return ONLY one valid JSON object containing the fields that must change. This is a merge patch, not a full replacement.
Do not return markdown, explanation, unchanged fields, or generation-only metadata.

Rules:
1. Preserve identity, reference source, work, version, established facts, and unrelated behavior unless the requested scope explicitly permits them.
2. Never add biography, trauma, expertise, relationships, private facts, dependency, exclusivity, romance, or loyalty that the user did not request.
3. A request for shorter, less theatrical, less repetitive, warmer, calmer, or more direct speech should change voice/examples/triggers, not identity.
4. Runtime examples must include a concrete user turn and an actual good assistant reply. Do not output abstract descriptions as examples.
5. Keep task, analysis, emotional, crisis, safety, and privacy behavior useful before expressive.
6. Respect the confirmed generation intent and its explicit constraints.
7. Arrays in returned fields replace existing arrays. Return the complete corrected array whenever changing one.
8. The fixed surface persona layer must remain {"layer_id":"surface","unlock_condition":null,"modifiers":{}}.

# Output Contract
Return a JSON patch using only schema fields allowed by the requested scope.

# Stage Quality Checks
1. The patch directly addresses the instruction.
2. The patch does not rewrite unrelated sections.
3. The patch does not introduce unsupported facts."""


_ALLOWED_ROOTS_BY_SCOPE = {
    "voice": frozenset({"idiolect", "registers", "bootstrap"}),
    "expression": frozenset(
        {"idiolect", "registers", "quiet_hours", "signature_triggers", "bootstrap"}
    ),
    "behavior": frozenset(
        {
            "identity_core",
            "registers",
            "quiet_hours",
            "signature_triggers",
            "persona_layers",
            "dynamic_state_rules",
            "milestone_conditions",
            "bootstrap",
        }
    ),
    "auto": frozenset(
        {
            "idiolect",
            "registers",
            "quiet_hours",
            "signature_triggers",
            "persona_layers",
            "dynamic_state_rules",
            "milestone_conditions",
            "bootstrap",
        }
    ),
}


def _filter_adjustment_patch(payload: dict[str, Any], scope: str) -> dict[str, Any]:
    allowed = _ALLOWED_ROOTS_BY_SCOPE.get(scope, _ALLOWED_ROOTS_BY_SCOPE["auto"])
    return {key: value for key, value in payload.items() if key in allowed}


async def adjust_personality_config(
    current_config: PersonalityConfigModel,
    instruction: str,
    *,
    scope: str = "auto",
    target_language: str = "English",
    intent: Optional[PersonaGenerationIntentModel] = None,
    llm_override: Optional[LLMSettings] = None,
    adapter_resolver: Callable[..., Any] = resolve_adapter_for_scenario,
    adapter_factory: Callable[..., Any] = create_llm_adapter,
) -> PersonalityConfigModel:
    """Apply one user-requested adjustment while preserving unrelated fields."""
    prompt = f"""# Target Language
{target_language}

# Adjustment Scope
{scope}

# Confirmed Generation Intent
{json.dumps(intent.model_dump() if intent is not None else None, ensure_ascii=False, indent=2)}

# User Adjustment
{instruction}

# Current Persona Configuration
{json.dumps(current_config.model_dump(), ensure_ascii=False, indent=2)}

# Task
Return only the smallest valid JSON patch that applies the adjustment."""
    raw_patch = await _run_generation_stage(
        stage_id="adjust",
        prompt=prompt,
        system_prompt=PERSONA_ADJUSTMENT_SYSTEM_PROMPT,
        max_tokens=2400,
        temperature=0.35,
        llm_override=llm_override,
        adapter_resolver=adapter_resolver,
        adapter_factory=adapter_factory,
        retry_on_json_error=True,
    )
    filtered_patch = _filter_adjustment_patch(raw_patch, scope)
    merged = copy.deepcopy(current_config.model_dump())
    _deep_merge_payload(merged, filtered_patch)
    normalized = normalize_generated_personality_payload(
        merged,
        target_language=target_language,
    )
    return PersonalityConfigModel.model_validate(normalized)


__all__ = [
    "PERSONA_ADJUSTMENT_SYSTEM_PROMPT",
    "adjust_personality_config",
]
