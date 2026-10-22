"""Durable selection and interrupted-cutover fence for structured repositories."""

from __future__ import annotations
from pathlib import Path
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict
from magi_plugin_sdk.fs import atomic_write_managed_bytes, read_managed_bytes


class StorageTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["sqlite", "mysql"]
    identity: str


class StorageTransferIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination: StorageTarget
    snapshot_digest: str
    replace_destination: bool = False


class StorageBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
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
        atomic_write_managed_bytes(self._path, binding.model_dump_json().encode())
