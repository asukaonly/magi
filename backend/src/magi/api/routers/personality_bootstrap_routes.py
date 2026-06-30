"""Bootstrap dialogue and persona journal routes."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from ... import i18n as core_i18n
from .personality_config_common import legacy_personality_config_module
from .personality_config_schemas import (
    BootstrapInitRequest,
    JournalReflectRequest,
    PersonalityResponse,
)

personality_bootstrap_router = APIRouter()


def _bootstrap_already_initialized_response() -> PersonalityResponse:
    return PersonalityResponse(
        success=True,
        message=core_i18n.t(
            "personality.bootstrap.opening_already_initialized",
            fallback="Bootstrap opening already initialized",
        ),
        data={
            "bootstrap_active": False,
            "opening": None,
            "needs_bootstrap_init": False,
            "bootstrap_completed": True,
        },
    )


def _bootstrap_no_opening_response(runtime_status: dict[str, Any]) -> PersonalityResponse:
    return PersonalityResponse(
        success=True,
        message=core_i18n.t(
            "personality.bootstrap.no_opening_available", fallback="No opening available"
        ),
        data={
            "bootstrap_active": False,
            "opening": None,
            "needs_bootstrap_init": True,
            "bootstrap_completed": False,
            "startup_state": runtime_status.get("startup_state"),
            "deferred_reason": runtime_status.get("deferred_reason"),
        },
    )


def _bootstrap_opening_injected_response(
    opening: str,
    runtime_status: dict[str, Any],
) -> PersonalityResponse:
    return PersonalityResponse(
        success=True,
        message=core_i18n.t(
            "personality.bootstrap.opening_injected",
            fallback="Bootstrap opening injected",
        ),
        data={
            "bootstrap_active": False,
            "opening": opening,
            "needs_bootstrap_init": False,
            "bootstrap_completed": True,
            "startup_state": runtime_status.get("startup_state"),
            "deferred_reason": runtime_status.get("deferred_reason"),
        },
    )


def _log_bootstrap_runtime_fallback(legacy: Any, runtime_status: dict[str, Any]) -> None:
    if runtime_status.get("llm_ready"):
        return
    legacy.logger.info(
        "Bootstrap init proceeding with static opening fallback while runtime startup is incomplete "
        "(startup_state=%s, deferred_reason=%s)",
        runtime_status.get("startup_state"),
        runtime_status.get("deferred_reason"),
    )


async def _persist_bootstrap_opening(
    *,
    legacy: Any,
    bootstrap_svc: Any,
    request: BootstrapInitRequest,
    current_name: str,
    persona_id: str,
    opening: str,
    turn_id: str,
) -> None:
    try:
        await legacy._persist_bootstrap_assistant_message(
            session_id=request.session_id,
            user_id=request.user_id,
            turn_id=turn_id,
            content=opening,
        )
        await bootstrap_svc.mark_bootstrap_started(
            persona_name=current_name,
            persona_id=persona_id,
            user_id=request.user_id,
            session_id=request.session_id,
            turn_id=turn_id,
        )
    except RuntimeError as exc:
        message = str(exc)
        if "binding is not initialized" in message:
            legacy.logger.info(
                "Bootstrap opening not persisted yet because runtime bindings are still starting: %s",
                exc,
            )
        else:
            legacy.logger.warning("Bootstrap opening not persisted (runtime not ready): %s", exc)


async def _run_bootstrap_init(
    legacy: Any,
    request: BootstrapInitRequest,
) -> PersonalityResponse:
    current_name = legacy.get_current_personality_name()
    persona_id = await legacy._resolve_persona_id(current_name)
    bootstrap_svc = await legacy._get_bootstrap_service()

    needs_bootstrap_init = await bootstrap_svc.needs_bootstrap_init(
        current_name, persona_id=persona_id
    )
    if not needs_bootstrap_init:
        return _bootstrap_already_initialized_response()

    runtime_status = await legacy._wait_for_bootstrap_runtime_ready()
    _log_bootstrap_runtime_fallback(legacy, runtime_status)

    opening = await bootstrap_svc.get_opening(current_name, persona_id=persona_id)
    if not opening:
        return _bootstrap_no_opening_response(runtime_status)

    turn_id = f"turn_bs_{uuid.uuid4().hex[:12]}"
    await _persist_bootstrap_opening(
        legacy=legacy,
        bootstrap_svc=bootstrap_svc,
        request=request,
        current_name=current_name,
        persona_id=persona_id,
        opening=opening,
        turn_id=turn_id,
    )
    return _bootstrap_opening_injected_response(opening, runtime_status)


@personality_bootstrap_router.post(
    "/bootstrap/init",
    response_model=PersonalityResponse,
    summary="Initialize bootstrap dialogue",
    description="Generate the persona opening line, persist it as a real chat message, and emit a notification.",
)
async def api_bootstrap_init(request: BootstrapInitRequest):
    legacy = legacy_personality_config_module()
    try:
        return await _run_bootstrap_init(legacy, request)
    except Exception as exc:
        legacy.logger.error("Bootstrap init failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@personality_bootstrap_router.post(
    "/journal/reflect",
    response_model=PersonalityResponse,
    summary="Trigger a persona journal reflection",
    description="Generate a persona-perspective reflection entry and store it as a milestone.",
)
async def api_journal_reflect(request: JournalReflectRequest):
    legacy = legacy_personality_config_module()
    try:
        persona_name = request.persona_name or legacy.get_current_personality_name()
        journal_svc = await legacy._get_journal_service()

        entry = await journal_svc.generate_reflection(
            persona_name=persona_name,
            emotional_state=request.emotional_state,
            relationship=request.relationship,
            recent_milestones=request.recent_milestones,
        )

        if entry is None:
            return PersonalityResponse(
                success=False,
                message=core_i18n.t(
                    "personality.journal.reflection_generation_failed",
                    fallback="Reflection generation failed",
                ),
                data=None,
            )

        return PersonalityResponse(
            success=True,
            message=core_i18n.t(
                "personality.journal.reflection_generated",
                fallback="Journal reflection generated",
            ),
            data={
                "milestone_id": entry.milestone_id,
                "content": entry.content,
                "timestamp": entry.timestamp,
            },
        )
    except Exception as exc:
        legacy.logger.error("Journal reflection failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


__all__ = ["api_bootstrap_init", "api_journal_reflect", "personality_bootstrap_router"]
