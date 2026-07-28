"""User prompts for staged personality generation."""

from __future__ import annotations

import json
from typing import Any, Optional, Sequence

from ...routers.personality_config_schemas import (
    PersonaGenerationIntentModel,
    PersonalityConfigModel,
)
from .normalization import _generation_meta_design
from .quality import _quality_findings_block
from .reference import (
    _generation_intent_block,
    _reference_profile_block,
)


def _current_config_block(
    current_config: Optional[PersonalityConfigModel],
) -> str:
    if current_config is None:
        return ""
    return "\n\n# Existing Draft Config\n" + json.dumps(
        current_config.model_dump(),
        ensure_ascii=False,
        indent=2,
    )


def _base_user_prompt(
    description: str,
    target_language: str,
    current_config: Optional[PersonalityConfigModel],
    intent: Optional[PersonaGenerationIntentModel] = None,
    reference_profile: Optional[dict[str, Any]] = None,
) -> str:
    return f"""# User Context
Target Language: {target_language}

# User Input
{description}{_current_config_block(current_config)}

{_generation_intent_block(intent)}{_reference_profile_block(reference_profile, "base")}

# Task
Extract the stable persona spine. Preserve explicit user-authored draft fields when they clearly conflict with generated guesses."""


def _module_user_prompt(
    description: str,
    target_language: str,
    spine: dict[str, Any],
    current_config: Optional[PersonalityConfigModel],
    task: str,
    intent: Optional[PersonaGenerationIntentModel] = None,
    reference_profile: Optional[dict[str, Any]] = None,
    stage_id: str = "",
) -> str:
    meta_design = _generation_meta_design(spine)
    return f"""# User Context
Target Language: {target_language}

# User Input
{description}{_current_config_block(current_config)}

{_generation_intent_block(intent)}{_reference_profile_block(reference_profile, stage_id)}

# Persona Spine
{json.dumps(spine, ensure_ascii=False, indent=2)}

# Design Anchors
The persona's design intent is captured in _meta_design within the spine. All outputs from this stage MUST serve these anchors:

- core_theme: {meta_design["core_theme"]}
- failure_mode_to_avoid: {meta_design["failure_mode"]}
- key_constraint: {meta_design["key_constraint"]}

If your output drifts toward the failure_mode_to_avoid, revise before returning.

# Module Task
{task}"""


def _integration_user_prompt(
    description: str,
    target_language: str,
    combined: dict[str, Any],
    intent: Optional[PersonaGenerationIntentModel] = None,
    findings: Optional[Sequence[str]] = None,
    reference_profile: Optional[dict[str, Any]] = None,
) -> str:
    return f"""# User Context
Target Language: {target_language}

# User Input
{description}

{_generation_intent_block(intent)}{_reference_profile_block(reference_profile, "integrate")}{_quality_findings_block(findings)}

# Combined Draft
{json.dumps(combined, ensure_ascii=False, indent=2)}

# Task
Conduct the cross-field consistency review from the system prompt. Identify the fields that contradict each other or fail to support the persona's _meta_design, and return ONLY those corrected fields. Omit anything already coherent, and return an empty object {{}} if nothing needs changing. Follow the output contract in the system prompt: mirror the draft's key paths, and for any array you change return the complete corrected array.

Pay particular attention to:
- Whether chat register examples resist the declared failure mode without including bad examples in the final runtime examples
- Whether vocab and sentence_style declarations match what examples actually demonstrate
- Whether crisis register meets safety-first requirements without inventing region-specific resources
- Whether relationship layers feel like the same character at different depths

Return only the JSON patch, no commentary, and do not include _meta_design."""
