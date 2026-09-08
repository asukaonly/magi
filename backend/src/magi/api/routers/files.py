"""Authenticated owner-facing center filesystem selection routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..services.center_files import CenterDirectory, CenterPathError, browse_center_directory, create_center_directory

from ..services.file_transfers import CHUNK_BYTES, TransferError, UploadSpec, UploadState, append_upload, begin_upload

from ..services.portability_downloads import OutputChunk, OutputMetadata, describe_output, read_output_chunk

files_router = APIRouter()


class CreateCenterDirectoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent: str = Field(min_length=1, max_length=4096)
    name: str = Field(min_length=1, max_length=255)


@files_router.get("/browse", response_model=CenterDirectory)
async def browse(path: str | None = Query(default=None, max_length=4096),
                 directories_only: bool = False, resolve_file: bool = False, after: str | None = Query(default=None, max_length=255),
                 prefix: str = Query(default="", max_length=255), show_hidden: bool = False,
                 limit: int = Query(default=200, ge=1, le=500)) -> CenterDirectory:
    try:
        return await browse_center_directory(path, directories_only=directories_only, after=after,
                                             prefix=prefix, show_hidden=show_hidden, limit=limit, resolve_file=resolve_file)
    except CenterPathError as error:
        raise HTTPException(status_code=error.status, detail={"error_code": error.code}) from error


@files_router.post("/directories", response_model=CenterDirectory)
async def create_directory(payload: CreateCenterDirectoryRequest) -> CenterDirectory:
    try:
        return await create_center_directory(payload.parent, payload.name)
    except CenterPathError as error:
        raise HTTPException(status_code=error.status, detail={"error_code": error.code}) from error



@files_router.post("/uploads", response_model=UploadState)
async def create_upload(payload: UploadSpec) -> UploadState:
    try:
        return await begin_upload(payload)
    except TransferError as error:
        raise HTTPException(error.status, detail={"error_code": error.code}) from error


@files_router.put("/uploads/{resource_id}", response_model=UploadState)
async def upload_chunk(resource_id: str, request: Request, offset: int = Query(ge=0),
                       sha256: str = Query(min_length=64, max_length=64)) -> UploadState:
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > CHUNK_BYTES:
            raise HTTPException(413, detail={"error_code": "resource_chunk_too_large"})
        chunks.extend(chunk)
    try:
        return await append_upload(resource_id, offset, bytes(chunks), sha256)
    except TransferError as error:
        raise HTTPException(error.status, detail={"error_code": error.code}) from error


@files_router.get("/outputs/{operation_id}", response_model=OutputMetadata)
async def describe_portability_output(operation_id: str) -> OutputMetadata:
    try:
        return await describe_output(operation_id)
    except TransferError as error:
        raise HTTPException(error.status, detail={"error_code": error.code}) from error


@files_router.get("/outputs/{operation_id}/chunks", response_model=OutputChunk)
async def download_portability_chunk(operation_id: str, offset: int = Query(ge=0),
                                     version: str = Query(pattern=r"^[0-9a-f]{64}$")) -> OutputChunk:
    try:
        return await read_output_chunk(operation_id, offset, version)
    except TransferError as error:
        raise HTTPException(error.status, detail={"error_code": error.code}) from error
