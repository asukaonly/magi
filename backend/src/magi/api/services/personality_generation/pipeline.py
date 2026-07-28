"""Top-level personality generation pipeline."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from ....config.models import LLMSettings
from ....llm import create_llm_adapter
from ....llm.draft import resolve_adapter_for_scenario
from ....personality.reference_research import ReferenceDossier
from ....personality.reference_research.ports import (
    ReferenceFetchPort,
    ReferenceSearchPort,
)
from ...routers.personality_config_schemas import (
    PersonaGenerationIntentModel,
    PersonalityConfigModel,
)
from .constants import GENERATION_STAGE_DEFINITIONS
from .contracts import (
    PersonalityGenerationResult,
    _GenerationRunContext,
)
from .normalization import (
    _runtime_payload_from_combined,
    normalize_generated_personality_payload,
)
from .normalization_primitives import _resolve_generation_target_language
from .reference import (
    _merge_reference_profile_with_dossier,
    _run_reference_profile_stage,
    _run_reference_research_stage,
)
from .runtime import logger
from .stage_pipeline import (
    _record_completed_generation_stage,
    _run_base_personality_stage,
    _run_integration_personality_stage,
    _run_module_personality_stages,
)


def _stage_reports(
    status_by_id: dict[str, str],
) -> list[dict[str, str]]:
    return [
        {
            "stage_id": item["stage_id"],
            "label": item["label"],
            "status": status_by_id.get(
                item["stage_id"],
                "completed",
            ),
        }
        for item in GENERATION_STAGE_DEFINITIONS
    ]


def _initial_stage_reports() -> list[dict[str, str]]:
    return [
        {
            "stage_id": item["stage_id"],
            "label": item["label"],
            "status": "pending",
        }
        for item in GENERATION_STAGE_DEFINITIONS
    ]


def _set_stage_status(
    stages: list[dict[str, str]],
    stage_id: str,
    status: str,
) -> None:
    for item in stages:
        if item.get("stage_id") == stage_id:
            item["status"] = status
            return
    stages.append(
        {
            "stage_id": stage_id,
            "label": stage_id,
            "status": status,
        }
    )


async def generate_personality_config_result(
    description: str,
    target_language: str = "English",
    current_config: Optional[PersonalityConfigModel] = None,
    llm_override: Optional[LLMSettings] = None,
    intent: Optional[PersonaGenerationIntentModel] = None,
    *,
    adapter_resolver: Callable[..., Any] = resolve_adapter_for_scenario,
    adapter_factory: Callable[..., Any] = create_llm_adapter,
    stage_progress_callback: Optional[Callable[[str, str], None]] = None,
    search_port: Optional[ReferenceSearchPort] = None,
    fetch_port: Optional[ReferenceFetchPort] = None,
) -> PersonalityGenerationResult:
    """Generate personality configuration through staged LLM calls."""
    stage_status: list[dict[str, str]] = []
    resolved_target_language = _resolve_generation_target_language(
        description,
        target_language,
        current_config,
    )
    context = _GenerationRunContext(
        description=description,
        target_language=resolved_target_language,
        current_config=current_config,
        llm_override=llm_override,
        intent=intent,
        adapter_resolver=adapter_resolver,
        adapter_factory=adapter_factory,
        stage_progress_callback=stage_progress_callback,
        search_port=search_port,
        fetch_port=fetch_port,
    )
    try:
        if context.stage_progress_callback is not None:
            context.stage_progress_callback(
                "reference",
                "running",
            )
        reference_profile = await _run_reference_profile_stage(context)
        reference_dossier = await _run_reference_research_stage(
            context,
            reference_profile,
        )
        grounded_profile = _merge_reference_profile_with_dossier(
            reference_profile,
            reference_dossier,
        )
        _record_completed_generation_stage(
            stage_status,
            context,
            "reference",
        )
        combined = await _run_base_personality_stage(
            context,
            stage_status,
            grounded_profile,
        )
        await _run_module_personality_stages(
            context,
            stage_status,
            combined,
            grounded_profile,
        )
        await _run_integration_personality_stage(
            context,
            stage_status,
            combined,
            grounded_profile,
        )
        return _build_personality_generation_result(
            combined,
            stage_status,
            target_language=context.target_language,
            reference_dossier=reference_dossier,
        )
    except json.JSONDecodeError as exc:
        logger.error(
            "[AI Generate Personality] JSON decode failed: %s",
            exc,
        )
        raise ValueError(f"AI returned invalid JSON format: {exc}") from exc
    except Exception:
        logger.error("[AI Generate Personality] Generation failed")
        raise


def _build_personality_generation_result(
    combined: dict[str, Any],
    stage_status: list[dict[str, str]],
    *,
    target_language: str,
    reference_dossier: Optional[ReferenceDossier] = None,
) -> PersonalityGenerationResult:
    data = normalize_generated_personality_payload(
        _runtime_payload_from_combined(combined),
        target_language=target_language,
    )
    if not data.get("name"):
        data["name"] = "AI Assistant"
    status_by_id = {item["stage_id"]: item["status"] for item in stage_status}
    return PersonalityGenerationResult(
        config=PersonalityConfigModel(**data),
        stages=_stage_reports(status_by_id),
        reference_dossier=reference_dossier,
    )


async def generate_personality_config(
    description: str,
    target_language: str = "English",
    current_config: Optional[PersonalityConfigModel] = None,
    llm_override: Optional[LLMSettings] = None,
    intent: Optional[PersonaGenerationIntentModel] = None,
    *,
    adapter_resolver: Callable[..., Any] = resolve_adapter_for_scenario,
    adapter_factory: Callable[..., Any] = create_llm_adapter,
    search_port: Optional[ReferenceSearchPort] = None,
    fetch_port: Optional[ReferenceFetchPort] = None,
) -> PersonalityConfigModel:
    """Generate personality configuration from description using LLM."""
    result = await generate_personality_config_result(
        description,
        target_language=target_language,
        current_config=current_config,
        llm_override=llm_override,
        intent=intent,
        adapter_resolver=adapter_resolver,
        adapter_factory=adapter_factory,
        search_port=search_port,
        fetch_port=fetch_port,
    )
    return result.config
