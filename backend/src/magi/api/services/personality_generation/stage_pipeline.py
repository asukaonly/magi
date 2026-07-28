"""Execution of the persona-specific generation stages."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Optional, Sequence

from ..personality_generation_prompts import (
    APPEARANCE_SYSTEM_PROMPT,
    BASE_SPINE_SYSTEM_PROMPT,
    BOOTSTRAP_SYSTEM_PROMPT,
    INTEGRATION_SYSTEM_PROMPT,
    LAYERS_SYSTEM_PROMPT,
    REGISTER_SYSTEM_PROMPT,
    RULES_SYSTEM_PROMPT,
)
from .constants import META_DESIGN_KEY
from .contracts import _GenerationRunContext
from .model_stages import (
    _run_generation_stage,
    _run_optional_generation_stage,
)
from .normalization import (
    _complete_generation_meta_design,
    _deep_merge_payload,
    _pick_keys,
)
from .prompting import (
    _base_user_prompt,
    _integration_user_prompt,
    _module_user_prompt,
)
from .quality import _generation_quality_findings
from .runtime import logger


async def _run_base_personality_stage(
    context: _GenerationRunContext,
    stage_status: list[dict[str, str]],
    reference_profile: Optional[dict[str, Any]],
) -> dict[str, Any]:
    base_data = await _run_generation_stage(
        stage_id="base",
        prompt=_base_user_prompt(
            context.description,
            context.target_language,
            context.current_config,
            context.intent,
            reference_profile,
        ),
        system_prompt=BASE_SPINE_SYSTEM_PROMPT,
        max_tokens=1600,
        temperature=0.55,
        **_generation_stage_dependencies(context),
    )
    _record_completed_generation_stage(
        stage_status,
        context,
        "base",
    )
    combined = _pick_keys(
        base_data,
        (
            "name",
            "avatar",
            "description",
            META_DESIGN_KEY,
            "identity_core",
            "idiolect",
        ),
    )
    _complete_generation_meta_design(combined)
    return combined


async def _run_module_personality_stages(
    context: _GenerationRunContext,
    stage_status: list[dict[str, str]],
    combined: dict[str, Any],
    reference_profile: Optional[dict[str, Any]],
) -> None:
    module_tasks = [
        _module_stage_task(
            context,
            stage_status,
            combined,
            allowed_keys=("registers",),
            stage_id="registers",
            system_prompt=REGISTER_SYSTEM_PROMPT,
            max_tokens=2000,
            temperature=0.7,
            task_prompt=(
                "Design all required registers with good-only runtime examples "
                "that match the spine and respect the persona's design anchors."
            ),
            reference_profile=reference_profile,
        ),
        _module_stage_task(
            context,
            stage_status,
            combined,
            allowed_keys=(
                "quiet_hours",
                "signature_triggers",
                "dynamic_state_rules",
                "milestone_conditions",
            ),
            stage_id="rules",
            system_prompt=RULES_SYSTEM_PROMPT,
            max_tokens=1500,
            temperature=0.7,
            task_prompt=(
                "Design the persona's trigger signatures, quiet-hour clamps, "
                "and state convergence rules using _meta_design as the source "
                "of persona-specific trigger ideas."
            ),
            reference_profile=reference_profile,
        ),
        _module_stage_task(
            context,
            stage_status,
            combined,
            allowed_keys=("persona_layers",),
            stage_id="layers",
            system_prompt=LAYERS_SYSTEM_PROMPT,
            max_tokens=1300,
            temperature=0.7,
            task_prompt=(
                "Design only the fixed surface baseline and non-surface deep "
                "persona layers as concrete diffs from the same _meta_design "
                "core theme."
            ),
            reference_profile=reference_profile,
        ),
        _module_stage_task(
            context,
            stage_status,
            combined,
            allowed_keys=(
                "registers",
                "bootstrap",
                "interim_lines",
            ),
            stage_id="bootstrap",
            system_prompt=BOOTSTRAP_SYSTEM_PROMPT,
            max_tokens=1800,
            temperature=0.72,
            task_prompt=(
                "Write good-only register examples, bootstrap first-contact "
                "copy that fits _meta_design, and sparse interim lines."
            ),
            reference_profile=reference_profile,
        ),
        _module_stage_task(
            context,
            stage_status,
            combined,
            allowed_keys=("appearance_prompt",),
            stage_id="appearance",
            system_prompt=APPEARANCE_SYSTEM_PROMPT,
            max_tokens=350,
            temperature=0.55,
            task_prompt="Write the portrait prompt only.",
            reference_profile=reference_profile,
        ),
    ]
    for fragment in await asyncio.gather(*module_tasks):
        _deep_merge_payload(combined, fragment)


def _module_stage_task(
    context: _GenerationRunContext,
    stage_status: list[dict[str, str]],
    combined: dict[str, Any],
    *,
    allowed_keys: Sequence[str],
    stage_id: str,
    system_prompt: str,
    max_tokens: int,
    temperature: float,
    task_prompt: str,
    reference_profile: Optional[dict[str, Any]],
) -> Awaitable[dict[str, Any]]:
    return _run_optional_generation_stage(
        stages=stage_status,
        allowed_keys=allowed_keys,
        stage_id=stage_id,
        prompt=_module_user_prompt(
            context.description,
            context.target_language,
            combined,
            context.current_config,
            task_prompt,
            context.intent,
            reference_profile,
            stage_id,
        ),
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        **_generation_stage_dependencies(context),
    )


async def _run_integration_personality_stage(
    context: _GenerationRunContext,
    stage_status: list[dict[str, str]],
    combined: dict[str, Any],
    reference_profile: Optional[dict[str, Any]],
) -> None:
    findings = _generation_quality_findings(
        combined,
        context.description,
        context.intent,
    )
    integration_completed = False
    if findings:
        logger.info(
            "[AI Generate Personality] Quality findings before integration: %s",
            findings,
        )
    try:
        integrated = await _run_generation_stage(
            stage_id="integrate",
            prompt=_integration_user_prompt(
                context.description,
                context.target_language,
                combined,
                context.intent,
                findings,
                reference_profile,
            ),
            system_prompt=INTEGRATION_SYSTEM_PROMPT,
            max_tokens=2048,
            temperature=0.4,
            retry_on_json_error=True,
            **_generation_stage_dependencies(context),
        )
        _deep_merge_payload(combined, integrated)
        integration_completed = True
    except Exception as exc:  # noqa: BLE001 - normalization can complete the draft
        logger.warning(
            "[AI Generate Personality] Integration stage failed: %s",
            exc,
        )
        if context.stage_progress_callback is not None:
            context.stage_progress_callback(
                "integrate",
                "failed",
            )
        stage_status.append(
            {
                "stage_id": "integrate",
                "status": "failed",
            }
        )

    remaining_findings = _generation_quality_findings(
        combined,
        context.description,
        context.intent,
    )
    if not remaining_findings:
        if integration_completed:
            _record_completed_generation_stage(
                stage_status,
                context,
                "integrate",
            )
        return
    logger.info(
        "[AI Generate Personality] Quality findings after integration: %s",
        remaining_findings,
    )
    try:
        repair = await _run_generation_stage(
            stage_id="integrate_quality_repair",
            prompt=_integration_user_prompt(
                context.description,
                context.target_language,
                combined,
                context.intent,
                remaining_findings,
                reference_profile,
            ),
            system_prompt=INTEGRATION_SYSTEM_PROMPT,
            max_tokens=1536,
            temperature=0.2,
            llm_override=context.llm_override,
            adapter_resolver=context.adapter_resolver,
            adapter_factory=context.adapter_factory,
            stage_progress_callback=None,
            retry_on_json_error=True,
        )
        _deep_merge_payload(combined, repair)
    except Exception as exc:  # noqa: BLE001 - known-bad draft cannot succeed
        raise ValueError("Persona quality repair failed after integration") from exc

    final_findings = _generation_quality_findings(
        combined,
        context.description,
        context.intent,
    )
    if final_findings:
        logger.warning(
            "[AI Generate Personality] Quality findings remain after repair: %s",
            final_findings,
        )
        raise ValueError("Persona quality checks still fail after repair")
    if integration_completed:
        _record_completed_generation_stage(
            stage_status,
            context,
            "integrate",
        )


def _record_completed_generation_stage(
    stage_status: list[dict[str, str]],
    context: _GenerationRunContext,
    stage_id: str,
) -> None:
    if context.stage_progress_callback is not None:
        context.stage_progress_callback(
            stage_id,
            "completed",
        )
    stage_status.append(
        {
            "stage_id": stage_id,
            "status": "completed",
        }
    )


def _generation_stage_dependencies(
    context: _GenerationRunContext,
) -> dict[str, Any]:
    return {
        "llm_override": context.llm_override,
        "adapter_resolver": context.adapter_resolver,
        "adapter_factory": context.adapter_factory,
        "stage_progress_callback": context.stage_progress_callback,
    }
