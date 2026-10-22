"""Read-only, connection-bound source queries shared by every source domain."""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, JsonValue, model_validator

from .runtime import RuntimeModel, SourceCoverage, SourceCoverageScope


class SourceScope(RuntimeModel):
    domain: str = Field(default="", max_length=128)
    provider: str = Field(default="", max_length=128)
    account: str = Field(default="", max_length=256)
    object_id: str = Field(default="", max_length=1024)
    thread_id: str = Field(default="", max_length=1024)

    @model_validator(mode="after")
    def unique_target(self) -> "SourceScope":
        if self.object_id and self.thread_id:
            raise ValueError("Select either an object or a thread")
        return self


class SourceQueryCapabilities(RuntimeModel):
    """A source opts into specific reads; registration does not grant invocation authority."""

    provider: str = Field(min_length=1, max_length=128)
    operations: list[Literal["search", "read", "thread"]] = Field(default_factory=lambda: ["search"])
    fields: list[str] = Field(default_factory=lambda: ["content"])
    max_page_size: int = Field(default=50, ge=1, le=100)
    supports_as_of: bool = False


class SourceQueryRequest(RuntimeModel):
    """Bounded content selection; credentials and connection identity are host-bound."""

    operation: Literal["search", "read", "thread"] = "search"
    scope: SourceCoverageScope = Field(default_factory=SourceCoverageScope)
    fields: list[str] = Field(default_factory=lambda: ["content"], max_length=100)
    as_of: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    limit: int = Field(default=20, ge=1, le=100)
    page_token: str | None = Field(default=None, max_length=65536)

    @model_validator(mode="after")
    def reads_require_identity(self) -> "SourceQueryRequest":
        if self.operation != "search" and len(self.scope.object_ids) != 1:
            raise ValueError("Object and thread reads require exactly one identifier")
        return self


class SourceEvidence(RuntimeModel):
    """Versioned source evidence, distinct from an already committed memory event."""

    object_id: str = Field(min_length=1, max_length=1024)
    version: str = Field(min_length=1, max_length=256)
    text: str = Field(max_length=16384)
    title: str = Field(default="", max_length=1024)
    occurred_at: float | None = Field(default=None, allow_inf_nan=False)
    thread_id: str | None = Field(default=None, max_length=1024)
    fields: list[str] = Field(default_factory=lambda: ["content"])
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    url: str | None = Field(default=None, max_length=4096)


class SourceQueryResult(RuntimeModel):
    items: list[SourceEvidence] = Field(default_factory=list, max_length=100)
    coverage: SourceCoverage
    next_page_token: str | None = Field(default=None, max_length=65536)

    @model_validator(mode="after")
    def pages_are_partial(self) -> "SourceQueryResult":
        if self.next_page_token and self.coverage.completeness == "complete":
            raise ValueError("A paginated result cannot claim complete coverage")
        return self


@runtime_checkable
class QueryableSource(Protocol):
    """Optional capability implemented alongside the existing Source contract."""

    async def query_source(self, request: SourceQueryRequest) -> SourceQueryResult: ...
