"""Authenticated owner-facing center filesystem selection routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ..services.center_files import CenterDirectory, CenterPathError, browse_center_directory, create_center_directory

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
