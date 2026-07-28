"""In-memory background job lifecycle for personality generation."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable, Optional

from ....config.models import LLMSettings
from ....llm import create_llm_adapter
from ....llm.draft import resolve_adapter_for_scenario
from ....personality.reference_research.ports import (
    ReferenceFetchPort,
    ReferenceSearchPort,
)
from ...routers.personality_config_schemas import (
    PersonaGenerationIntentModel,
    PersonalityConfigModel,
)
from .constants import PERSONALITY_GENERATION_JOB_TTL_SECONDS
from .contracts import PersonalityGenerationJob
from .pipeline import (
    _initial_stage_reports,
    _set_stage_status,
    generate_personality_config_result,
)


_PERSONALITY_GENERATION_JOBS: dict[str, PersonalityGenerationJob] = {}
_PERSONALITY_GENERATION_REQUEST_INDEX: dict[str, str] = {}


def _personality_generation_job_snapshot(
    job: PersonalityGenerationJob,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_id": job.job_id,
        "status": job.status,
        "stages": [dict(item) for item in job.stages],
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }
    if job.draft_id:
        payload["draft_id"] = job.draft_id
    if job.request_id:
        payload["request_id"] = job.request_id
    if job.result is not None:
        payload["data"] = job.result.config.model_dump()
        payload["stages"] = job.result.stages
        if job.result.reference_dossier is not None:
            payload["reference_dossier"] = job.result.reference_dossier.model_dump()
    if job.error:
        payload["error"] = job.error
    if job.error_code:
        payload["error_code"] = job.error_code
    return payload


def _cleanup_personality_generation_jobs(
    now: Optional[float] = None,
) -> None:
    current_time = now or time.time()
    ttl_seconds = PERSONALITY_GENERATION_JOB_TTL_SECONDS
    try:
        from ....config import get_config

        ttl_seconds = get_config().lifecycle.ephemeral_jobs.personality_generation_ttl_seconds
    except Exception:
        ttl_seconds = PERSONALITY_GENERATION_JOB_TTL_SECONDS
    expired_ids = [
        job_id
        for job_id, job in _PERSONALITY_GENERATION_JOBS.items()
        if current_time - job.updated_at > ttl_seconds
    ]
    for job_id in expired_ids:
        _PERSONALITY_GENERATION_JOBS.pop(job_id, None)
    if expired_ids:
        expired_set = set(expired_ids)
        for request_id, job_id in list(_PERSONALITY_GENERATION_REQUEST_INDEX.items()):
            if job_id in expired_set:
                _PERSONALITY_GENERATION_REQUEST_INDEX.pop(
                    request_id,
                    None,
                )


async def start_personality_generation_job(
    description: str,
    target_language: str = "English",
    current_config: Optional[PersonalityConfigModel] = None,
    llm_override: Optional[LLMSettings] = None,
    draft_id: Optional[str] = None,
    request_id: Optional[str] = None,
    intent: Optional[PersonaGenerationIntentModel] = None,
    *,
    adapter_resolver: Callable[..., Any] = resolve_adapter_for_scenario,
    adapter_factory: Callable[..., Any] = create_llm_adapter,
    search_port: Optional[ReferenceSearchPort] = None,
    fetch_port: Optional[ReferenceFetchPort] = None,
) -> dict[str, Any]:
    """Start a background persona generation job and return its snapshot."""
    _cleanup_personality_generation_jobs()
    if request_id:
        existing_job_id = _PERSONALITY_GENERATION_REQUEST_INDEX.get(request_id)
        existing_job = _PERSONALITY_GENERATION_JOBS.get(existing_job_id or "")
        if existing_job is not None:
            return _personality_generation_job_snapshot(existing_job)
    now = time.time()
    job = PersonalityGenerationJob(
        job_id=str(uuid.uuid4()),
        status="running",
        stages=_initial_stage_reports(),
        created_at=now,
        updated_at=now,
        draft_id=draft_id,
        request_id=request_id,
    )
    _PERSONALITY_GENERATION_JOBS[job.job_id] = job
    if request_id:
        _PERSONALITY_GENERATION_REQUEST_INDEX[request_id] = job.job_id
    asyncio.create_task(
        _run_personality_generation_job(
            job,
            description=description,
            target_language=target_language,
            current_config=current_config,
            llm_override=llm_override,
            intent=intent,
            adapter_resolver=adapter_resolver,
            adapter_factory=adapter_factory,
            search_port=search_port,
            fetch_port=fetch_port,
        )
    )
    return _personality_generation_job_snapshot(job)


async def get_personality_generation_job(
    job_id: str,
) -> Optional[dict[str, Any]]:
    """Return a generation job snapshot if it is still available."""
    _cleanup_personality_generation_jobs()
    job = _PERSONALITY_GENERATION_JOBS.get(job_id)
    if job is None:
        return None
    return _personality_generation_job_snapshot(job)


async def _run_personality_generation_job(
    job: PersonalityGenerationJob,
    *,
    description: str,
    target_language: str,
    current_config: Optional[PersonalityConfigModel],
    llm_override: Optional[LLMSettings],
    intent: Optional[PersonaGenerationIntentModel],
    adapter_resolver: Callable[..., Any],
    adapter_factory: Callable[..., Any],
    search_port: Optional[ReferenceSearchPort],
    fetch_port: Optional[ReferenceFetchPort],
) -> None:
    def update_stage(stage_id: str, status: str) -> None:
        _set_stage_status(job.stages, stage_id, status)
        job.updated_at = time.time()

    try:
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
            stage_progress_callback=update_stage,
        )
        job.result = result
        job.stages = result.stages
        job.status = "completed"
        job.updated_at = time.time()
    except Exception as exc:  # noqa: BLE001 - surfaced through status endpoint
        job.error = str(exc)
        job.error_code = getattr(exc, "code", None)
        job.status = "failed"
        job.updated_at = time.time()
