"""Bounded public host-service values; no host adapters or authority selectors."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

HostMethod = Literal["memory.search", "interaction.ask"]
HOST_METHODS: tuple[HostMethod, ...] = ("memory.search", "interaction.ask")
HOST_SERVICE_PERMISSIONS: dict[HostMethod, tuple[str, str]] = {
    "memory.search": ("memory_search", "current_user"),
    "interaction.ask": ("interaction_ask", "current_session"),
}


class HostServiceValue(BaseModel):
    """Strict JSON values validated on both sides of the RPC boundary."""

    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, allow_inf_nan=False
    )


class MemorySearchRequest(HostServiceValue):
    query: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    limit: int = Field(default=5, ge=1, le=10)


class MemoryFinding(HostServiceValue):
    """Answer-facing evidence with no raw records, paths or internal metadata."""

    statement: str = Field(min_length=1, max_length=2000)
    source_layer: Literal["L1", "L2", "L3", "L4"]
    kind: Literal[
        "event", "relationship", "assertion", "experience", "reflection", "procedure"
    ]
    occurred_at: float | None = None
    status: str | None = Field(default=None, max_length=128)
    evidence_semantics: str | None = Field(default=None, max_length=128)
    correction_status: str | None = Field(default=None, max_length=128)
    evidence_text: str | None = Field(default=None, max_length=2000)
    truncated: bool = False


class MemorySearchResult(HostServiceValue):
    status: Literal["found", "not_found", "ambiguous", "conflicted"]
    summary: str = Field(max_length=2000)
    findings: list[MemoryFinding] = Field(default_factory=list, max_length=10)
    insufficient_evidence: bool
    truncated: bool = False


AskOption = Annotated[
    str, StringConstraints(min_length=1, max_length=200, pattern=r"\S")
]


class AskUserRequest(HostServiceValue):
    question: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    options: list[AskOption] = Field(default_factory=list, max_length=6)
    allow_free_text: bool = True
    timeout_seconds: float = Field(default=60.0, ge=1.0, le=300.0)

    @model_validator(mode="after")
    def answer_is_possible(self) -> AskUserRequest:
        if not self.allow_free_text and not self.options:
            raise ValueError("Ask requests require options or free text")
        if len(set(self.options)) != len(self.options):
            raise ValueError("Ask options must be distinct")
        return self


class AskUserResult(HostServiceValue):
    answered: bool
    answer: str | None = Field(default=None, max_length=16000)
    resolution: Literal["user", "cancelled", "timeout"]
    timed_out: bool

    @model_validator(mode="after")
    def consistent_outcome(self) -> AskUserResult:
        if self.answered != (self.resolution == "user"):
            raise ValueError("Answer state must match its resolution")
        if self.timed_out != (self.resolution == "timeout"):
            raise ValueError("Timeout state must match its resolution")
        if (self.answer is not None) != self.answered:
            raise ValueError("Only answered requests may contain an answer")
        return self


__all__ = [
    "HOST_METHODS",
    "HOST_SERVICE_PERMISSIONS",
    "AskUserRequest",
    "AskUserResult",
    "HostMethod",
    "MemoryFinding",
    "MemorySearchRequest",
    "MemorySearchResult",
]
