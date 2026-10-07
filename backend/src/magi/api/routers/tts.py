"""Authenticated generation API; no playback or public resource URLs."""

import hashlib
from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from magi.config.loader import config_write_guard, get_config, save_config
from magi.core.runtime_bindings import require_chat_read_service
from magi.identity import CANONICAL_LOCAL_USER
from magi.speech.tts.contracts import (
    MessageSource, SynthesisJob, SynthesisRequest, TTSConfiguration,
    TTSConfigurationUpdate, TTSModelStatus,
)
from magi.speech.tts.catalog import choices
from magi.speech.tts.engines import resolve_options
from magi.speech.tts.models import MODEL_ID, TTSModelStore
from magi.speech.tts.service import SynthesisService, fingerprint
from magi.utils.runtime import get_runtime_paths


def caller(request: Request) -> str:
    # The gateway removes caller-supplied values and injects its authenticated client ID.
    client = request.headers.get("x-magi-client-id")
    if not client:
        raise HTTPException(401, "client_auth_required")
    return fingerprint({"user": CANONICAL_LOCAL_USER, "client": client})


tts_router = APIRouter(dependencies=[Depends(caller)])
_service: SynthesisService | None = None


async def read_message(source: MessageSource) -> str:
    message = await require_chat_read_service().aget_display_message(
        CANONICAL_LOCAL_USER, source.session_id, source.message_id, final_only=True)
    if (not message or message.role != "assistant" or message.kind != "assistant"
            or message.message_kind not in {"assistant_final", "assistant_rhythm_segment"}
            or hashlib.sha256(message.content.encode()).hexdigest() != source.revision):
        raise ValueError("stale_message")
    return message.content


def service() -> SynthesisService:
    global _service
    if _service is None:
        paths = get_runtime_paths()
        _service = SynthesisService(paths.cache_dir / "tts", TTSModelStore(paths.models_cache_dir / "tts"), read_message)
    return _service


@asynccontextmanager
async def tts_clear_boundary() -> AsyncIterator[None]:
    # Initialize even after a restart so receipts and WAVs participate in full clear.
    async with service().clear_boundary():
        yield


def api_error(exc: ValueError) -> HTTPException:
    code = str(exc)
    status = 404 if code == "not_found" else 410 if code == "audio_expired" else 409 if code in {
        "request_conflict", "stale_message", "synthesis_closed", "content_clearing", "config_conflict", "model_busy"
    } else 429 if code == "capacity_exceeded" else 422
    return HTTPException(status, code)


@tts_router.get("/settings", response_model=TTSConfiguration)
async def settings() -> TTSConfiguration:
    config = get_config()
    selection = config.speech.tts
    return TTSConfiguration(settings=selection, revision=fingerprint(selection.model_dump()),
                            models=choices(config, service().models))


@tts_router.put("/settings", response_model=TTSConfiguration)
async def update_settings(body: TTSConfigurationUpdate) -> TTSConfiguration:
    with config_write_guard():
        config = get_config()
        if fingerprint(config.speech.tts.model_dump()) != body.revision:
            raise HTTPException(409, "config_conflict")
        candidate = config.model_copy(deep=True)
        candidate.speech.tts = body.settings
        try:
            resolve_options(candidate)
        except ValueError as exc:
            raise api_error(exc) from exc
        if not save_config({"speech.tts": body.settings.model_dump()}):
            raise HTTPException(500, "config_save_failed")
    return await settings()


@tts_router.post("/syntheses", status_code=202, response_model=SynthesisJob)
async def create(body: SynthesisRequest, owner: str = Depends(caller)) -> SynthesisJob:
    try:
        # Receipt lookup precedes configuration resolution: unknown requests never become retries.
        try:
            existing = await service().by_request(owner, str(body.request_id))
        except ValueError as exc:
            if str(exc) != "not_found":
                raise
        else:
            receipt = service().owned(owner, existing.job_id)
            if receipt.identity not in {fingerprint(body.identity()), "cancelled"}:
                raise ValueError("request_conflict")
            return existing
        config = get_config().model_copy(deep=True)
        if body.preview_settings is not None:
            config.speech.tts = body.preview_settings
        return await service().create(owner, body, resolve_options(config))
    except ValueError as exc:
        raise api_error(exc) from exc


@tts_router.get("/syntheses/by-request/{request_id}", response_model=SynthesisJob)
async def by_request(request_id: UUID, owner: str = Depends(caller)) -> SynthesisJob:
    try:
        return await service().by_request(owner, str(request_id))
    except ValueError as exc:
        raise api_error(exc) from exc


@tts_router.post("/syntheses/by-request/{request_id}/cancel", response_model=SynthesisJob)
async def cancel_request(request_id: UUID, owner: str = Depends(caller)) -> SynthesisJob:
    try:
        return await service().cancel_request(owner, str(request_id))
    except ValueError as exc:
        raise api_error(exc) from exc


@tts_router.get("/syntheses/{job_id}", response_model=SynthesisJob)
async def get_job(job_id: UUID, owner: str = Depends(caller)) -> SynthesisJob:
    try:
        return await service().get(owner, str(job_id))
    except ValueError as exc:
        raise api_error(exc) from exc


@tts_router.post("/syntheses/{job_id}/segments/{seq}", status_code=202, response_model=SynthesisJob)
async def advance(job_id: UUID, seq: int, owner: str = Depends(caller)) -> SynthesisJob:
    try:
        return await service().advance(owner, str(job_id), seq)
    except ValueError as exc:
        raise api_error(exc) from exc


@tts_router.post("/syntheses/{job_id}/cancel", response_model=SynthesisJob)
async def cancel(job_id: UUID, owner: str = Depends(caller)) -> SynthesisJob:
    try:
        return service().cancel(owner, str(job_id))
    except ValueError as exc:
        raise api_error(exc) from exc


@tts_router.get("/syntheses/{job_id}/segments/{seq}", response_class=Response)
async def audio(job_id: UUID, seq: int, owner: str = Depends(caller)) -> Response:
    try:
        clip = await service().segment(owner, str(job_id), seq)
    except ValueError as exc:
        raise api_error(exc) from exc
    return Response(clip.data, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@tts_router.get("/models", response_model=TTSModelStatus)
async def model_status(model_id: str = MODEL_ID) -> TTSModelStatus:
    try:
        return service().models.get(model_id).snapshot()
    except ValueError as exc:
        raise api_error(exc) from exc


@tts_router.post("/models/download", response_model=TTSModelStatus)
async def download(model_id: str = MODEL_ID) -> TTSModelStatus:
    try:
        return service().models.get(model_id).download(get_config().network.proxy_url())
    except ValueError as exc:
        raise api_error(exc) from exc


@tts_router.post("/models/download/cancel", response_model=TTSModelStatus)
async def cancel_download(model_id: str = MODEL_ID) -> TTSModelStatus:
    try:
        return await service().models.get(model_id).cancel()
    except ValueError as exc:
        raise api_error(exc) from exc


@tts_router.delete("/models", response_model=TTSModelStatus)
async def delete_model(model_id: str = MODEL_ID) -> TTSModelStatus:
    service()._expire()
    if any(
        receipt.job.engine == "local" and receipt.job.model == model_id and receipt.job.state in {"ready", "running", "cancelling"}
        for receipt in service().receipts.values()
    ):
        raise HTTPException(409, "model_busy")
    try:
        result = service().models.get(model_id).delete()
        service().engine.unload_if_idle(model_id)
        return result
    except ValueError as exc:
        raise api_error(exc) from exc
