"""Typed contracts for personality generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from ....config.models import LLMSettings
from ....personality.reference_research import ReferenceDossier
from ....personality.reference_research.ports import (
    ReferenceFetchPort,
    ReferenceSearchPort,
)
from ...routers.personality_config_schemas import (
    PersonaGenerationIntentModel,
    PersonalityConfigModel,
)


@dataclass(frozen=True)
class PersonalityGenerationResult:
    """Generated persona plus stage reports for UI feedback."""

    config: PersonalityConfigModel
    stages: list[dict[str, str]]
    reference_dossier: Optional[ReferenceDossier] = None


@dataclass
class PersonalityGenerationJob:
    """In-memory state for a single persona generation request."""

    job_id: str
    status: str
    stages: list[dict[str, str]]
    created_at: float
    updated_at: float
    draft_id: Optional[str] = None
    request_id: Optional[str] = None
    result: Optional[PersonalityGenerationResult] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


@dataclass(frozen=True)
class _GenerationRunContext:
    description: str
    target_language: str
    current_config: Optional[PersonalityConfigModel]
    llm_override: Optional[LLMSettings]
    intent: Optional[PersonaGenerationIntentModel]
    adapter_resolver: Callable[..., Any]
    adapter_factory: Callable[..., Any]
    stage_progress_callback: Optional[Callable[[str, str], None]]
    search_port: Optional[ReferenceSearchPort] = None
    fetch_port: Optional[ReferenceFetchPort] = None
