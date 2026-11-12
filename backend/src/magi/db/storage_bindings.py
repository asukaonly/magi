"""Durable selection and interrupted-cutover fence for structured repositories."""

from __future__ import annotations
from pathlib import Path
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from magi_plugin_sdk.fs import atomic_write_managed_bytes, read_managed_bytes


class StorageTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str = Field(min_length=1, max_length=64)
    identity: str = Field(min_length=1, max_length=256)
    plugin_id: str = Field(min_length=1, max_length=128)
    connection_id: str = Field(pattern=r"^conn_[0-9a-f]{32}$")
    contract_version: Literal[1] = 1


class StorageTransferIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination: StorageTarget
    snapshot_digest: str
    replace_destination: bool = False


class StorageBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[2] = 2
    center_id: str
    active: StorageTarget | None = None
    pending: StorageTransferIntent | None = None


class StorageBindingFile:
    """Only the runtime or offline maintenance lease may update this file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read_or_create(self) -> StorageBinding:
        payload = read_managed_bytes(self._path, max_bytes=16384)
        if payload is not None:
            return StorageBinding.model_validate_json(payload)
        binding = StorageBinding(center_id=str(uuid4()))
        self.write(binding)
        return binding

    def write(self, binding: StorageBinding) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        atomic_write_managed_bytes(self._path, binding.model_dump_json().encode())
