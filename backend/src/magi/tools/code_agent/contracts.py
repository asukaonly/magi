"""Pydantic contracts shared across code_agent components."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...core.code_agent_artifacts import (
    normalize_code_agent_delegation_id,
)
from ...core.chat_assets.paths import normalize_chat_asset_component


AdapterName = Literal["claude_code", "codex"]
RunEventKind = Literal[
    "stdout", "stderr", "tool_call", "tool_result",
    "assistant_text", "thinking", "status", "error",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProbeResult(_Frozen):
    name: AdapterName
    installed: bool
    binary_path: Optional[str]
    version: Optional[str]
    detected_at: int = Field(ge=0)
    error: Optional[str]
    extras: dict[str, Any] = Field(default_factory=dict)


class DelegateConstraints(_Frozen):
    forbid_paths: list[str] = Field(default_factory=list)
    forbid_network: bool = False
    forbid_git_commit: bool = True
    forbid_git_push: bool = True
    max_budget_usd: Optional[float] = None
    allow_tools: Optional[list[str]] = None


class DelegateRequest(_Frozen):
    delegation_id: str
    session_id: str
    turn_id: str
    adapter: AdapterName
    prompt: str
    files_hint: list[str] = Field(default_factory=list)
    workspace_root: str
    constraints: DelegateConstraints
    timeout_s: int = Field(ge=10, le=3600)
    model: Optional[str] = None

    @field_validator("delegation_id")
    @classmethod
    def _check_delegation_id(cls, v: str) -> str:
        return normalize_code_agent_delegation_id(v)

    @field_validator("session_id")
    @classmethod
    def _check_session_id(cls, value: str) -> str:
        return normalize_chat_asset_component(value, label="session_id")

    @field_validator("turn_id")
    @classmethod
    def _check_turn_id(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("turn_id must not be blank")
        return normalized


class DiffStats(_Frozen):
    files_changed: int = Field(default=0, ge=0)
    additions: int = Field(default=0, ge=0)
    deletions: int = Field(default=0, ge=0)


class DiffSnapshot(_Frozen):
    stats: DiffStats
    files_changed: list[str] = Field(default_factory=list)
    unified_diff: str = ""
    status_porcelain: str = ""


class RunEvent(_Frozen):
    kind: RunEventKind
    ts_ms: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class CostInfo(_Frozen):
    usd: Optional[float] = None
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)


class DelegateResult(_Frozen):
    delegation_id: str
    success: bool
    exit_code: int
    duration_ms: int = Field(ge=0)
    adapter: AdapterName
    diff_path: Optional[str]
    diff_stats: DiffStats
    files_changed: list[str] = Field(default_factory=list)
    summary: Optional[str]
    logs_path: str
    events_path: str
    error: Optional[str]
    cost: Optional[CostInfo]
    artifact_registered: bool = False
    applied: bool = False
    applied_at: Optional[int] = Field(default=None, ge=0)
    applied_files: list[str] = Field(default_factory=list)
    cancelled: bool = False


__all__ = [
    "AdapterName",
    "RunEventKind",
    "ProbeResult",
    "DelegateConstraints",
    "DelegateRequest",
    "DiffStats",
    "DiffSnapshot",
    "RunEvent",
    "CostInfo",
    "DelegateResult",
]
