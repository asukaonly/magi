"""Authenticated, bounded WAV transcription and model management."""

from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse
from magi_plugin_sdk.audio import MAX_AUDIO_BYTES

from ...speech.asr.catalog import MODEL_ID
from ...speech.asr.contracts import ASRError, ASRJob, ASRModel, ASRModels, ASRStatus
from ...speech.asr.service import get_asr_service


class ASRRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            try:
                _identity(request)
                return await handler(request)
            except ASRError as exc:
                return JSONResponse(
                    {"success": False, "error_code": exc.code, "message": exc.code},
                    status_code=exc.status,
                )

        return handle


asr_router = APIRouter(route_class=ASRRoute)


def _identity(request: Request) -> str:
    peer = request.headers.get("x-magi-client-id")
    if not peer:
        raise ASRError("client_auth_required", 401)
    epoch = request.headers.get("x-magi-data-epoch")
    if not epoch or epoch != os.environ.get("MAGI_DATA_EPOCH"):
        raise ASRError("runtime_changed", 409)
    return peer


def _runtime(request: Request) -> str:
    return request.headers.get("x-magi-asr-runtime", "")


def _model(model_id: str) -> None:
    if model_id != MODEL_ID:
        raise ASRError("unknown_model", 404)


@asr_router.get("/status", response_model=ASRStatus)
async def status() -> ASRStatus:
    return await get_asr_service().status()


@asr_router.post("/transcriptions/{request_id}", response_model=ASRJob, status_code=202)
async def transcribe(request_id: str, request: Request) -> ASRJob:
    service = get_asr_service()
    service.check_runtime(_runtime(request))
    if request.headers.get("content-type", "").split(";", 1)[0] != "audio/wav":
        raise ASRError("invalid_audio", 415)
    audio = bytearray()
    async for chunk in request.stream():
        if len(audio) + len(chunk) > MAX_AUDIO_BYTES:
            raise ASRError("audio_too_large", 413)
        audio.extend(chunk)
    return await service.submit(
        _identity(request),
        _runtime(request),
        request_id,
        bytes(audio),
        config_revision=request.headers.get("x-magi-asr-config", ""),
    )


@asr_router.get("/transcriptions/{request_id}", response_model=ASRJob)
async def get_transcription(request_id: str, request: Request) -> ASRJob:
    return get_asr_service().get(_identity(request), _runtime(request), request_id)


@asr_router.post("/transcriptions/{request_id}/cancel", response_model=ASRJob)
async def cancel_transcription(request_id: str, request: Request) -> ASRJob:
    return get_asr_service().cancel(_identity(request), _runtime(request), request_id)


@asr_router.get("/models", response_model=ASRModels)
async def models() -> ASRModels:
    return ASRModels(models=[await get_asr_service().models.snapshot()])


@asr_router.post("/models/{model_id}/download", response_model=ASRModel)
async def download_model(model_id: str) -> ASRModel:
    _model(model_id)
    service = get_asr_service()
    async with service.admission:
        if service.local_in_use():
            raise ASRError("model_in_use", 409)
        return await service.models.download()


@asr_router.post("/models/{model_id}/download/cancel", response_model=ASRModel)
async def cancel_download(model_id: str) -> ASRModel:
    _model(model_id)
    return await get_asr_service().models.cancel()


@asr_router.delete("/models/{model_id}", response_model=ASRModel)
async def delete_model(model_id: str) -> ASRModel:
    _model(model_id)
    service = get_asr_service()
    async with service.admission:
        settings = service.config().speech.asr
        if service.local_in_use() or (
            settings.enabled and settings.mode == "local" and settings.local_model_id == model_id
        ):
            raise ASRError("model_in_use", 409)
        service.local.unload()
        return await service.models.delete()
