"""Pydantic record models for the workspace cache."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SCHEMA_VERSION = 1
_SHA256_HEX_LEN = 64


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _validate_sha256(v: str) -> str:
    if len(v) != _SHA256_HEX_LEN:
        raise ValueError(f"sha256 must be {_SHA256_HEX_LEN} hex chars")
    int(v, 16)
    return v


class ReadRecord(_Frozen):
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    line_count: int = Field(ge=0)
    mtime_ms: int = Field(ge=0)
    ts_ms: int = Field(ge=0)

    @field_validator("sha256")
    @classmethod
    def _check_hash(cls, v: str) -> str:
        return _validate_sha256(v)


EditOp = Literal["replace", "write", "delete"]


class EditRecord(_Frozen):
    path: str
    op: EditOp
    sha256_before: str
    sha256_after: str
    snapshot_ref: str
    ts_ms: int = Field(ge=0)

    @field_validator("sha256_before", "sha256_after", "snapshot_ref")
    @classmethod
    def _check_hash(cls, v: str) -> str:
        return _validate_sha256(v)


class SnapshotRef(_Frozen):
    sha256: str

    @field_validator("sha256")
    @classmethod
    def _check_hash(cls, v: str) -> str:
        return _validate_sha256(v)


class WorkspaceMetadata(_Frozen):
    workspace_root: str
    schema_version: int = SCHEMA_VERSION
    created_at_ms: int = Field(ge=0)
