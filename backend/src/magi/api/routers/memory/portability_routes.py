"""Memory backup, readable export, and restore job routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypeVar

from fastapi import HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ....memory.portability.errors import MemoryPortabilityError
from ....memory.portability.operations import MemoryPortabilityOperation
from ....memory.portability.service import get_memory_portability_service
from .router import memory_router

_MAX_PASSWORD_BYTES = 1024
_MAX_LOCAL_PATH_LENGTH = 4096
_MAX_REQUEST_BODY_BYTES = 16 * 1024
_RequestModel = TypeVar("_RequestModel", bound=BaseModel)


class CreateMemoryBackupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_directory: str
    encryption: Literal["password", "none"]
    password: object | None = Field(
        default=None,
        json_schema_extra={"type": "string", "format": "password"},
    )


class CreateMemoryExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_directory: str
    include_l0: bool = False


class InspectMemoryRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    password: object | None = Field(
        default=None,
        json_schema_extra={"type": "string", "format": "password"},
    )


@memory_router.post(
    "/portability/backups",
    response_model=MemoryPortabilityOperation,
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": CreateMemoryBackupRequest.model_json_schema(),
                }
            },
        }
    },
)
async def create_memory_backup(
    request: Request,
) -> MemoryPortabilityOperation:
    service = get_memory_portability_service()
    try:
        body = await _validated_request_body(request, CreateMemoryBackupRequest)
        password = _validated_password(body.password)
        if body.encryption == "password" and (password is None or not password.strip()):
            raise MemoryPortabilityError(
                "password_required",
                "A non-empty password is required for encrypted backup output.",
            )
        if body.encryption == "none" and password is not None:
            raise MemoryPortabilityError(
                "password_not_allowed",
                "A password cannot be supplied for an unencrypted backup.",
            )
        return await service.start_backup(
            destination_directory=_validated_local_path(body.destination_directory),
            encryption=body.encryption,
            password=password,
        )
    except MemoryPortabilityError as exc:
        _raise_portability_error(exc)


@memory_router.post(
    "/portability/exports",
    response_model=MemoryPortabilityOperation,
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": CreateMemoryExportRequest.model_json_schema(),
                }
            },
        }
    },
)
async def create_memory_export(
    request: Request,
) -> MemoryPortabilityOperation:
    service = get_memory_portability_service()
    try:
        body = await _validated_request_body(request, CreateMemoryExportRequest)
        return await service.start_export(
            destination_directory=_validated_local_path(body.destination_directory),
            include_l0=bool(body.include_l0),
        )
    except MemoryPortabilityError as exc:
        _raise_portability_error(exc)


@memory_router.post(
    "/portability/restores/inspect",
    response_model=MemoryPortabilityOperation,
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": InspectMemoryRestoreRequest.model_json_schema(),
                }
            },
        }
    },
)
async def inspect_memory_restore(
    request: Request,
) -> MemoryPortabilityOperation:
    service = get_memory_portability_service()
    try:
        body = await _validated_request_body(request, InspectMemoryRestoreRequest)
        return await service.start_inspection(
            source_path=_validated_local_path(body.source_path),
            password=_validated_password(body.password, blank_as_none=True),
        )
    except MemoryPortabilityError as exc:
        _raise_portability_error(exc)


@memory_router.post(
    "/portability/restores/{candidate_id}/confirm",
    response_model=MemoryPortabilityOperation,
    status_code=status.HTTP_202_ACCEPTED,
)
async def confirm_memory_restore(candidate_id: str) -> MemoryPortabilityOperation:
    service = get_memory_portability_service()
    try:
        return await service.start_restore(candidate_id=candidate_id)
    except MemoryPortabilityError as exc:
        _raise_portability_error(exc)


@memory_router.delete(
    "/portability/restores/{candidate_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def discard_memory_restore_candidate(candidate_id: str) -> Response:
    service = get_memory_portability_service()
    try:
        await service.delete_candidate(candidate_id=candidate_id)
    except MemoryPortabilityError as exc:
        _raise_portability_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@memory_router.get(
    "/portability/operations/active",
    response_model=MemoryPortabilityOperation | None,
)
async def get_active_memory_portability_operation() -> MemoryPortabilityOperation | None:
    try:
        return get_memory_portability_service().get_active_operation()
    except MemoryPortabilityError as exc:
        _raise_portability_error(exc)


@memory_router.get(
    "/portability/operations/latest",
    response_model=MemoryPortabilityOperation | None,
)
async def get_latest_memory_portability_operation() -> MemoryPortabilityOperation | None:
    try:
        return get_memory_portability_service().get_latest_operation()
    except MemoryPortabilityError as exc:
        _raise_portability_error(exc)


@memory_router.get(
    "/portability/operations/{operation_id}",
    response_model=MemoryPortabilityOperation,
)
async def get_memory_portability_operation(
    operation_id: str,
) -> MemoryPortabilityOperation:
    try:
        operation = get_memory_portability_service().get_operation(operation_id)
    except MemoryPortabilityError as exc:
        _raise_portability_error(exc)
    if operation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "operation_not_found",
                "message": "The memory data operation was not found.",
            },
        )
    return operation


def _validated_password(
    value: object | None,
    *,
    blank_as_none: bool = False,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MemoryPortabilityError(
            "password_invalid",
            "The backup password is invalid.",
        )
    password = value
    try:
        encoded_size = len(password.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise MemoryPortabilityError(
            "password_invalid",
            "The backup password is invalid.",
        ) from exc
    if encoded_size > _MAX_PASSWORD_BYTES:
        raise MemoryPortabilityError(
            "password_too_long",
            "The backup password is too long.",
        )
    if blank_as_none and not password.strip():
        return None
    return password


async def _validated_request_body(
    request: Request,
    model: type[_RequestModel],
) -> _RequestModel:
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > _MAX_REQUEST_BODY_BYTES:
                raise MemoryPortabilityError(
                    "request_too_large",
                    "The memory data request is too large.",
                    status_code=413,
                )
        except ValueError as exc:
            raise MemoryPortabilityError(
                "request_invalid",
                "The memory data request is invalid.",
            ) from exc

    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > _MAX_REQUEST_BODY_BYTES:
            raise MemoryPortabilityError(
                "request_too_large",
                "The memory data request is too large.",
                status_code=413,
            )
    try:
        raw = json.loads(payload)
        return model.model_validate(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise MemoryPortabilityError(
            "request_invalid",
            "The memory data request is invalid.",
        ) from exc


def _validated_local_path(value: str) -> Path:
    normalized = str(value or "")
    if not normalized.strip() or len(normalized) > _MAX_LOCAL_PATH_LENGTH or "\x00" in normalized:
        raise MemoryPortabilityError(
            "local_path_invalid",
            "The selected local path is invalid.",
        )
    return Path(normalized)


def _raise_portability_error(exc: MemoryPortabilityError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"error_code": exc.code, "message": str(exc)},
    ) from exc


__all__ = [
    "CreateMemoryBackupRequest",
    "CreateMemoryExportRequest",
    "InspectMemoryRestoreRequest",
]
