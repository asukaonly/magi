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
    TTSConfigurationUpdate, TTSModelStatus, VoiceInfo,
)
from magi.speech.tts.engines import remote_voices, resolve_options
from magi.speech.tts.models import LOCAL_VOICES, ModelManager
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
        _service = SynthesisService(paths.cache_dir / "tts", ModelManager(paths.models_cache_dir / "tts"), read_message)
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
    voices = LOCAL_VOICES if selection.engine == "local" else []
    if selection.engine == "remote":
        try:
            options = resolve_options(config)
            voices = [VoiceInfo(id=voice, language="multilingual") for voice in remote_voices(options.base_url, options.model)]
        except ValueError:
            pass
    return TTSConfiguration(settings=selection, revision=fingerprint(selection.model_dump()),
                            voices=voices, local_voices=LOCAL_VOICES, model=service().models.snapshot())


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
            if receipt.identity not in {fingerprint(body.source.model_dump()), "cancelled"}:
                raise ValueError("request_conflict")
            return existing
        return await service().create(owner, body, resolve_options(get_config()))
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
async def model_status() -> TTSModelStatus:
    return service().models.snapshot()


@tts_router.post("/models/download", response_model=TTSModelStatus)
async def download() -> TTSModelStatus:
    try:
        return service().models.download(get_config().network.proxy_url())
    except ValueError as exc:
        raise api_error(exc) from exc


@tts_router.post("/models/download/cancel", response_model=TTSModelStatus)
async def cancel_download() -> TTSModelStatus:
    return await service().models.cancel()


@tts_router.delete("/models", response_model=TTSModelStatus)
async def delete_model() -> TTSModelStatus:
    if any(
        receipt.job.engine == "local" and receipt.job.state in {"ready", "running", "cancelling"}
        for receipt in service().receipts.values()
    ):
        raise HTTPException(409, "model_busy")
    try:
        result = service().models.delete()
        service().engine.unload()
        return result
    except ValueError as exc:
        raise api_error(exc) from exc
