"""Reference-profile preparation and governed public research."""

from __future__ import annotations

import json
from typing import Any, Optional

from ....personality.reference_research import (
    ReferenceDossier,
    ReferenceIdentity,
    ReferenceResearchPolicyInput,
    decide_reference_research,
)
from ....personality.reference_research.service import (
    build_reference_fingerprint,
    calculate_profile_coverage,
    research_reference,
)
from ...routers.personality_config_schemas import (
    PersonaGenerationIntentModel,
)
from ..personality_generation_prompts import REFERENCE_PROFILE_SYSTEM_PROMPT
from ..personality_reference_tools import (
    ToolReferenceFetchAdapter,
    ToolReferenceSearchAdapter,
)
from .contracts import _GenerationRunContext
from .model_stages import _run_generation_stage
from .normalization_primitives import _string_list
from .runtime import logger


REFERENCE_PROFILE_DIMENSIONS = (
    "ordinary_baseline",
    "judgment_patterns",
    "speech_rhythm",
    "interaction_patterns",
    "signature_markers",
    "contrast_contexts",
    "version_notes",
)
REFERENCE_PROFILE_STAGE_DIMENSIONS = {
    "base": (
        "ordinary_baseline",
        "judgment_patterns",
        "speech_rhythm",
        "version_notes",
    ),
    "registers": (
        "ordinary_baseline",
        "speech_rhythm",
        "interaction_patterns",
        "contrast_contexts",
    ),
    "rules": ("signature_markers", "contrast_contexts"),
    "layers": ("interaction_patterns", "contrast_contexts"),
    "bootstrap": (
        "ordinary_baseline",
        "speech_rhythm",
        "interaction_patterns",
        "signature_markers",
    ),
    "appearance": (),
    "integrate": REFERENCE_PROFILE_DIMENSIONS,
}
REFERENCE_PROFILE_CONFIDENCE_VALUES = {"low", "medium", "high"}


def _generation_intent_block(
    intent: Optional[PersonaGenerationIntentModel],
) -> str:
    if intent is None:
        return """# Resolved Generation Intent
No user-confirmed reference resolution was provided. Infer conservatively from the description, do not claim reference fidelity, and do not invent unsupported identity facts."""
    return "# Resolved Generation Intent\n" + json.dumps(
        intent.model_dump(),
        ensure_ascii=False,
        indent=2,
    )


def _should_prepare_reference_profile(
    intent: Optional[PersonaGenerationIntentModel],
) -> bool:
    return bool(
        intent is not None
        and intent.reference is not None
        and intent.reference.user_confirmed
        and intent.source_kind in {"fictional_reference", "public_person_reference"}
    )


def _normalize_reference_profile_payload(
    payload: dict[str, Any],
    intent: PersonaGenerationIntentModel,
) -> dict[str, Any]:
    reference = intent.reference
    if reference is None:
        raise ValueError("Referenced persona profile requires a confirmed reference")
    raw_dimensions = payload.get("dimensions")
    if not isinstance(raw_dimensions, dict):
        raw_dimensions = {}
    dimensions = {
        key: _string_list(raw_dimensions.get(key))[:8] for key in REFERENCE_PROFILE_DIMENSIONS
    }
    raw_confidence = payload.get("confidence_by_dimension")
    if not isinstance(raw_confidence, dict):
        raw_confidence = {}
    confidence_by_dimension: dict[str, str] = {}
    for key in REFERENCE_PROFILE_DIMENSIONS:
        value = str(raw_confidence.get(key) or "").strip().lower()
        if value in REFERENCE_PROFILE_CONFIDENCE_VALUES:
            confidence_by_dimension[key] = value
    raw_volatility = str(payload.get("volatility") or "unknown")
    return {
        "provenance_kind": "parametric_prior",
        "reference": {
            "source_kind": reference.source_kind,
            "name": reference.name,
            "work_title": reference.work_title,
            "version": reference.version,
        },
        "dimensions": dimensions,
        "volatility": (
            raw_volatility
            if raw_volatility in {"stable", "evolving", "current", "unknown"}
            else "unknown"
        ),
        "unknowns": _string_list(payload.get("unknowns"))[:12],
        "confidence_by_dimension": confidence_by_dimension,
    }


def _reference_profile_user_prompt(
    description: str,
    target_language: str,
    intent: PersonaGenerationIntentModel,
) -> str:
    return f"""# User Context
Target Language: {target_language}

# User Input
{description}

{_generation_intent_block(intent)}

# Task
Prepare the unverified parametric-prior reference profile described in the system prompt. Keep uncertainty explicit and do not design the final persona."""


def _reference_profile_block(
    reference_profile: Optional[dict[str, Any]],
    stage_id: str,
) -> str:
    if not reference_profile:
        return ""
    dimension_keys = REFERENCE_PROFILE_STAGE_DIMENSIONS.get(
        stage_id,
        REFERENCE_PROFILE_DIMENSIONS,
    )
    dimensions = reference_profile.get("dimensions")
    if not isinstance(dimensions, dict):
        dimensions = {}
    sliced = {
        "provenance_kind": reference_profile.get(
            "provenance_kind",
            "parametric_prior",
        ),
        "reference": reference_profile.get("reference", {}),
        "dimensions": {key: dimensions.get(key, []) for key in dimension_keys},
        "unknowns": reference_profile.get("unknowns", []),
        "confidence_by_dimension": {
            key: value
            for key, value in dict(reference_profile.get("confidence_by_dimension") or {}).items()
            if key in dimension_keys
        },
        "source_ids": reference_profile.get("source_ids", []),
        "grounding_status": reference_profile.get(
            "grounding_status",
            "model_prior",
        ),
        "contradictions": reference_profile.get("contradictions", []),
    }
    provenance = str(sliced["provenance_kind"])
    if provenance == "public_sources":
        boundary = (
            "This profile contains public-source-backed behavioral evidence. "
            "Use only the distilled claims and their source IDs. Do not extend "
            "them into unsupported biography, private facts, relationships, "
            "expertise, or verbatim imitation. Contradictions and unknowns "
            "remain unresolved. User-confirmed input overrides it."
        )
        title = "Source-backed Reference Profile"
    else:
        boundary = (
            "This profile comes from model parametric memory. It is not verified "
            "evidence and has no sources. Use it as a behavioral prior only. "
            "Never turn uncertain biography, relationships, expertise, or "
            "private details into facts. User-confirmed input overrides it."
        )
        title = "Unverified Reference Profile"
    return f"\n\n# {title}\n" + json.dumps(sliced, ensure_ascii=False, indent=2) + f"\n\n{boundary}"


async def _run_reference_profile_stage(
    context: _GenerationRunContext,
) -> Optional[dict[str, Any]]:
    if not _should_prepare_reference_profile(context.intent):
        return None
    intent = context.intent
    if intent is None:
        return None
    try:
        payload = await _run_generation_stage(
            stage_id="reference_profile",
            prompt=_reference_profile_user_prompt(
                context.description,
                context.target_language,
                intent,
            ),
            system_prompt=REFERENCE_PROFILE_SYSTEM_PROMPT,
            max_tokens=1300,
            temperature=0.2,
            llm_override=context.llm_override,
            adapter_resolver=context.adapter_resolver,
            adapter_factory=context.adapter_factory,
            stage_progress_callback=None,
        )
        return _normalize_reference_profile_payload(payload, intent)
    except Exception as exc:  # noqa: BLE001 - existing generation path remains available
        logger.warning(
            "[AI Generate Personality] Reference profile stage failed: %s",
            exc,
        )
        return None


def _reference_identity_from_intent(
    intent: Optional[PersonaGenerationIntentModel],
) -> Optional[ReferenceIdentity]:
    if (
        intent is None
        or intent.reference is None
        or intent.source_kind not in {"fictional_reference", "public_person_reference"}
    ):
        return None
    reference = intent.reference
    return ReferenceIdentity(
        source_kind=reference.source_kind,
        name=reference.name,
        work_title=reference.work_title,
        version=reference.version,
        context=reference.context,
    )


def _prior_reference_dossier(
    identity: ReferenceIdentity,
    reference_profile: Optional[dict[str, Any]],
    *,
    research_level: str = "none",
    grounding_status: str = "model_prior",
    warning: Optional[str] = None,
) -> ReferenceDossier:
    dimensions = reference_profile.get("dimensions") if isinstance(reference_profile, dict) else {}
    if not isinstance(dimensions, dict):
        dimensions = {}
    normalized_dimensions = {
        key: _string_list(dimensions.get(key))[:8] for key in REFERENCE_PROFILE_DIMENSIONS
    }
    return ReferenceDossier(
        reference_fingerprint=build_reference_fingerprint(identity),
        identity_status="unverified",
        grounding_status=grounding_status,
        research_level=research_level,
        canonical_identity=identity,
        profile_dimensions=normalized_dimensions,
        unknowns=(
            _string_list(reference_profile.get("unknowns"))[:16]
            if isinstance(reference_profile, dict)
            else []
        ),
        coverage=calculate_profile_coverage(reference_profile),
        volatility=(reference_profile or {}).get("volatility", "unknown"),
        sufficient=False,
        warning=warning,
    )


async def _run_reference_research_stage(
    context: _GenerationRunContext,
    reference_profile: Optional[dict[str, Any]],
) -> Optional[ReferenceDossier]:
    """Apply one policy to all public and fictional references."""
    identity = _reference_identity_from_intent(context.intent)
    intent = context.intent
    if identity is None or intent is None:
        return None
    profile_coverage = calculate_profile_coverage(reference_profile)
    volatility = str((reference_profile or {}).get("volatility") or "unknown")
    decision = decide_reference_research(
        ReferenceResearchPolicyInput(
            source_kind=intent.source_kind,
            fidelity_level=intent.fidelity_level,
            research_preference=intent.research.preference,
            identity_confidence=intent.research.identity_confidence,
            identity_ambiguous=intent.research.identity_ambiguous,
            identity_verified=intent.research.identity_verified,
            reference_modified=intent.research.reference_modified,
            profile_coverage=profile_coverage,
            volatility=volatility,
            has_user_reference_urls=bool(intent.research.reference_urls),
        )
    )
    if decision.blocked_reason == "faithful_requires_research":
        raise ValueError("Faithful reference generation requires public-source verification")
    if not decision.requires_network:
        grounding_status = "disabled" if intent.research.preference == "disabled" else "model_prior"
        return _prior_reference_dossier(
            identity,
            reference_profile,
            research_level=decision.level,
            grounding_status=grounding_status,
            warning=(
                "Public-source verification was disabled."
                if grounding_status == "disabled"
                else "Generated from the model's unverified prior knowledge."
            ),
        )

    search_port = context.search_port or ToolReferenceSearchAdapter()
    fetch_port = context.fetch_port or ToolReferenceFetchAdapter()
    dossier = await research_reference(
        identity,
        research_level=decision.level,
        target_language=context.target_language,
        search_port=search_port,
        fetch_port=fetch_port,
        reference_urls=intent.research.reference_urls,
        force_refresh=intent.research.force_refresh,
        llm_override=context.llm_override,
        adapter_resolver=context.adapter_resolver,
        adapter_factory=context.adapter_factory,
    )
    if intent.fidelity_level == "faithful" and not dossier.sufficient:
        raise ValueError("Public sources are insufficient for faithful reference generation")
    return dossier


def _merge_reference_profile_with_dossier(
    reference_profile: Optional[dict[str, Any]],
    dossier: Optional[ReferenceDossier],
) -> Optional[dict[str, Any]]:
    if dossier is None:
        return reference_profile
    prior_dimensions = (
        reference_profile.get("dimensions") if isinstance(reference_profile, dict) else {}
    )
    if not isinstance(prior_dimensions, dict):
        prior_dimensions = {}
    source_dimensions = dossier.profile_dimensions
    dimensions = {
        key: (
            list(source_dimensions.get(key) or [])
            if source_dimensions.get(key)
            else _string_list(prior_dimensions.get(key))[:8]
        )
        for key in REFERENCE_PROFILE_DIMENSIONS
    }
    canonical = dossier.canonical_identity
    return {
        "provenance_kind": (
            "public_sources"
            if dossier.sources and dossier.grounding_status in {"verified", "insufficient"}
            else "parametric_prior"
        ),
        "reference": (canonical.model_dump() if canonical is not None else {}),
        "dimensions": dimensions,
        "unknowns": dossier.unknowns,
        "contradictions": dossier.contradictions,
        "confidence_by_dimension": {
            key: "high" if source_dimensions.get(key) else "medium"
            for key in REFERENCE_PROFILE_DIMENSIONS
            if dimensions.get(key)
        },
        "source_ids": [source.source_id for source in dossier.sources],
        "grounding_status": dossier.grounding_status,
        "volatility": dossier.volatility,
    }
