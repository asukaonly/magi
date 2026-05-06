"""REST API for the code_agent settings page (probe + settings CRUD).

Endpoints (under ``/api/code_agent``):

* ``GET  /probe``               cached or fresh probe of claude_code + codex
* ``POST /rescan``              force-reprobe both adapters
* ``GET  /settings``            merged user+project settings
* ``PATCH /settings``           deep-merge a partial patch into user or project toml
* ``POST /settings/reset``      delete a project-level toml override
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ...core.logger import get_logger
from ...tools.code_agent.probe import probe_all
from ...tools.code_agent.settings import load_settings
from ...tools.code_agent.settings_writer import (
    reset_project_settings,
    write_project_settings,
    write_user_settings,
)


logger = get_logger(__name__)
code_agent_router = APIRouter()


@code_agent_router.get("/probe")
def get_probe(force: bool = False) -> dict[str, Any]:
    results = probe_all(force=force)
    return {"results": {name: r.model_dump() for name, r in results.items()}}


@code_agent_router.post("/rescan")
def post_rescan() -> dict[str, Any]:
    results = probe_all(force=True)
    return {"results": {name: r.model_dump() for name, r in results.items()}}


@code_agent_router.get("/settings")
def get_settings(workspace: Optional[str] = None) -> dict[str, Any]:
    workspace_path: Optional[Path] = Path(workspace) if workspace else None
    s = load_settings(workspace_root=workspace_path)
    return {
        "settings": s.model_dump(),
        "workspace_used": str(workspace_path) if workspace_path else None,
    }


class _PatchSettingsBody(BaseModel):
    level: Literal["user", "project"]
    patch: dict[str, Any] = Field(default_factory=dict)
    workspace: Optional[str] = None


@code_agent_router.patch("/settings")
def patch_settings(body: _PatchSettingsBody) -> dict[str, Any]:
    if body.level == "project" and not body.workspace:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="level=project requires workspace",
        )
    if not isinstance(body.patch, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="patch must be an object",
        )

    if body.level == "user":
        write_user_settings(body.patch)
    else:
        assert body.workspace is not None
        write_project_settings(Path(body.workspace), body.patch)

    workspace_path = Path(body.workspace) if body.workspace else None
    s = load_settings(workspace_root=workspace_path)
    return {
        "settings": s.model_dump(),
        "workspace_used": str(workspace_path) if workspace_path else None,
    }


class _ResetSettingsBody(BaseModel):
    level: Literal["project"]
    workspace: str


@code_agent_router.post("/settings/reset")
def post_reset(body: _ResetSettingsBody) -> dict[str, Any]:
    reset_project_settings(Path(body.workspace))
    return {"ok": True}


__all__ = ["code_agent_router"]
