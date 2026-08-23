"""Durable contracts for tool calls that may produce external effects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ToolEffectReplayPolicy(str, Enum):
    """Whether an ambiguous tool attempt may be executed again automatically."""

    READ_ONLY = "read_only"
    IDEMPOTENT = "idempotent"
    IDEMPOTENT_WITH_KEY = "idempotent_with_key"
    NON_IDEMPOTENT = "non_idempotent"
    RECONCILABLE = "reconcilable"
    UNKNOWN = "unknown"

    @property
    def requires_ledger(self) -> bool:
        return self is not self.READ_ONLY

    def permits_ambiguous_retry(self, *, has_idempotency_key: bool) -> bool:
        if self is self.IDEMPOTENT:
            return True
        if self is self.IDEMPOTENT_WITH_KEY:
            return has_idempotency_key
        return False


class ToolEffectState(str, Enum):
    """Durable state of one effect attempt."""

    ATTEMPTING = "attempting"
    SUCCEEDED = "succeeded"
    FAILED_NO_EFFECT = "failed_no_effect"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class ToolEffectIntent:
    """Privacy-minimized identity persisted immediately before execution."""

    semantic_key: str
    scope_id: str
    user_id: str | None
    session_id: str | None
    turn_id: str | None
    task_id: str | None
    tool_call_id: str | None
    tool_name: str
    replay_policy: ToolEffectReplayPolicy
    arguments_digest: str
    idempotency_key_digest: str | None = None


@dataclass(frozen=True, slots=True)
class ToolEffectAdmission:
    """Result of atomically recording an intent or detecting ambiguity."""

    attempt_id: str | None
    blocked_by_attempt_id: str | None = None
    blocked_state: ToolEffectState | None = None

    @property
    def admitted(self) -> bool:
        return self.attempt_id is not None


class ToolEffectLedger(Protocol):
    """Persistence seam owned by the canonical tool invocation service."""

    async def begin_tool_effect(
        self,
        intent: ToolEffectIntent,
        *,
        permit_ambiguous_retry: bool,
    ) -> ToolEffectAdmission: ...

    async def finish_tool_effect(
        self,
        *,
        attempt_id: str,
        state: ToolEffectState,
        error_code: str | None = None,
    ) -> None: ...


__all__ = [
    "ToolEffectAdmission",
    "ToolEffectIntent",
    "ToolEffectLedger",
    "ToolEffectReplayPolicy",
    "ToolEffectState",
]
