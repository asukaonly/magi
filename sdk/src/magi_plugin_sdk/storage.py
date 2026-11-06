"""Versioned storage contribution protocol; database handles never cross IPC."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

StorageDomain = Literal["chat", "memory_events", "channels"]


class StorageContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class StorageProviderSpec(StorageContract):
    provider_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    contract_version: Literal[1] = 1
    domains: list[StorageDomain] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_domains(self) -> StorageProviderSpec:
        if len(set(self.domains)) != len(self.domains):
            raise ValueError("Storage domains must be unique")
        return self


class StorageOpen(StorageContract):
    domain: StorageDomain
    center_id: str = Field(min_length=1, max_length=128)
    mode: Literal["runtime", "maintenance"]
    migrate: bool = False


class StorageOpened(StorageContract):
    session_id: str = Field(min_length=1, max_length=128)
    target_identity: str = Field(min_length=1, max_length=256)
    schema_version: str = Field(min_length=1, max_length=128)


class StorageCall(StorageContract):
    session_id: str = Field(min_length=1, max_length=128)
    repository: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    operation: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$")
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class StorageResult(StorageContract):
    value: JsonValue = None
    error: Literal["conflict", "unavailable", "invalid", "not_found", "outcome_unknown"] | None = None


class StorageProvider(Protocol):
    """One connection owner; operations are allowlisted repository commands."""

    async def open(self, request: StorageOpen) -> StorageOpened: ...
    async def invoke(self, request: StorageCall) -> StorageResult: ...
    async def close(self, session_id: str) -> None: ...
