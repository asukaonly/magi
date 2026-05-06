"""REST API for the code_agent settings page + delegation control.

Endpoints (under ``/api/code_agent``):

* ``GET  /probe``                          cached or fresh probe of claude_code + codex
* ``POST /rescan``                         force-reprobe both adapters
* ``GET  /settings``                       merged user+project settings
* ``PATCH /settings``                      deep-merge a partial patch into user or project toml
* ``POST /settings/reset``                 delete a project-level toml override
* ``GET  /delegations/{sid}/{did}``        result + last-50 events for a delegation
* ``POST /delegations/{sid}/{did}/cancel`` flip cancel token of a running delegation
* ``POST /delegations/{sid}/{did}/apply``  git apply the diff to the workspace
* ``POST /delegations/{sid}/{did}/discard`` clean up worktree, stamp result.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ...core.logger import get_logger
from ...tools.code_agent.apply_diff import apply_delegation, discard_delegation
from ...tools.code_agent.probe import probe_all
from ...tools.code_agent.service import CodeAgentService
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


# ---------------------------------------------------------------------------
# Delegation control endpoints
# ---------------------------------------------------------------------------

class _WorkspaceBody(BaseModel):
    workspace: str


def _delegation_dir(workspace: Path, sid: str, did: str) -> Path:
    return workspace / ".magi" / "sessions" / sid / "delegations" / did


def _read_events_tail(events_path: Path, limit: int = 50) -> list[dict[str, Any]]:
    if not events_path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out[-limit:]


@code_agent_router.get("/delegations/{session_id}/{delegation_id}")
def get_delegation(
    session_id: str, delegation_id: str, workspace: Optional[str] = None,
) -> dict[str, Any]:
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workspace query parameter is required",
        )
    workspace_path = Path(workspace).resolve()
    delegation_dir = _delegation_dir(workspace_path, session_id, delegation_id)
    if not delegation_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"delegation not found: {delegation_id}",
        )
    result_path = delegation_dir / "result.json"
    result: Optional[dict[str, Any]]
    if result_path.is_file():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result = None
    else:
        result = None
    events_tail = _read_events_tail(delegation_dir / "events.jsonl", limit=50)
    return {"result": result, "events_tail": events_tail}


@code_agent_router.post("/delegations/{session_id}/{delegation_id}/cancel")
def post_cancel(
    session_id: str, delegation_id: str, body: _WorkspaceBody,
) -> dict[str, Any]:
    _ = session_id
    _ = body
    ok = CodeAgentService.cancel(delegation_id)
    return {"ok": ok}


@code_agent_router.post("/delegations/{session_id}/{delegation_id}/apply")
def post_apply(
    session_id: str, delegation_id: str, body: _WorkspaceBody,
) -> dict[str, Any]:
    workspace_path = Path(body.workspace).resolve()
    outcome = apply_delegation(
        workspace_root=workspace_path,
        session_id=session_id,
        delegation_id=delegation_id,
    )
    return {"outcome": outcome.to_dict()}


@code_agent_router.post("/delegations/{session_id}/{delegation_id}/discard")
def post_discard(
    session_id: str, delegation_id: str, body: _WorkspaceBody,
) -> dict[str, Any]:
    workspace_path = Path(body.workspace).resolve()
    discard_delegation(
        workspace_root=workspace_path,
        session_id=session_id,
        delegation_id=delegation_id,
    )
    return {"ok": True}


__all__ = ["code_agent_router"]
