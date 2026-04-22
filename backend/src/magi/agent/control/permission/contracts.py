"""Data contracts for the permission gateway.

All enums are string-valued so they survive JSON round-trips across
IPC / API boundaries without a custom encoder.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any

__all__ = [
    "PermissionDecision",
    "PermissionOutcome",
    "PermissionRequest",
    "PermissionRule",
    "PermissionScope",
    "RiskLevel",
    "ToolOrigin",
]


class RiskLevel(str, Enum):
    """Risk tier assigned to ``(tool, args)`` by the classifier.

    Ordering matters: comparisons use the integer ``order`` attribute
    to avoid string-compare surprises (``"destructive" < "high"`` would
    be wrong lexicographically).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DESTRUCTIVE = "destructive"
    KILL_LISTED = "kill_listed"

    @property
    def order(self) -> int:
        return _RISK_ORDER[self]

    def __ge__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, RiskLevel):
            return self.order >= other.order
        return NotImplemented

    def __gt__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, RiskLevel):
            return self.order > other.order
        return NotImplemented

    def __le__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, RiskLevel):
            return self.order <= other.order
        return NotImplemented

    def __lt__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, RiskLevel):
            return self.order < other.order
        return NotImplemented


_RISK_ORDER: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.DESTRUCTIVE: 3,
    RiskLevel.KILL_LISTED: 4,
}


class PermissionScope(str, Enum):
    """Scope attached to a user-created permission rule."""

    ONE_SHOT = "one_shot"
    SESSION = "session"
    PERSISTENT_EXACT = "persistent_exact"
    PERSISTENT_PATTERN = "persistent_pattern"


class PermissionOutcome(str, Enum):
    """Terminal result of a permission decision."""

    ALLOWED = "allowed"
    DENIED = "denied"
    KILL_LISTED = "kill_listed"
    TIMED_OUT = "timed_out"


class ToolOrigin(str, Enum):
    """Which subsystem initiated the tool call.

    Used by the gateway to tag decisions and, later, to decide whether
    the caller is allowed to promote rules (e.g. subagent calls cannot
    create persistent rules on behalf of the user).
    """

    CHAT = "chat"
    SUBAGENT = "subagent"
    SKILL = "skill"
    BACKGROUND = "background"
    SCHEDULED = "scheduled"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class PermissionRequest:
    """A single ``(tool, args)`` invocation awaiting a gate decision."""

    request_id: str
    tool_name: str
    arguments: dict[str, Any]
    risk_level: RiskLevel
    origin: ToolOrigin
    agent_id: str
    session_id: str | None
    task_id: str | None
    workspace: str | None
    #: Short human-facing preview (first N chars of command, diff summary…).
    preview: str | None = None
    #: Classifier signals that drove the risk tier (``["fs_write", "outside_workspace"]``).
    signals: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time)

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "risk_level": self.risk_level.value,
            "origin": self.origin.value,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "workspace": self.workspace,
            "preview": self.preview,
            "signals": list(self.signals),
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class PermissionDecision:
    """Outcome of evaluating a :class:`PermissionRequest`."""

    request_id: str
    outcome: PermissionOutcome
    #: ``"auto"``, ``"user"``, ``"rule:<rule_id>"``, ``"kill_list:<key>"``, ``"timeout"``
    source: str
    #: Optional human-readable rationale shown in the trace UI.
    reason: str | None = None
    #: If the user chose a persistent scope during the prompt, this is
    #: the rule that was (or should be) written.
    recorded_rule: "PermissionRule | None" = None
    decided_at: float = field(default_factory=time)

    @property
    def allowed(self) -> bool:
        return self.outcome is PermissionOutcome.ALLOWED

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "outcome": self.outcome.value,
            "source": self.source,
            "reason": self.reason,
            "recorded_rule": (
                self.recorded_rule.to_dict() if self.recorded_rule else None
            ),
            "decided_at": self.decided_at,
        }


@dataclass(slots=True)
class PermissionRule:
    """A user-authored rule that short-circuits future gate decisions.

    Matching semantics:

    * ``PERSISTENT_EXACT`` / ``SESSION`` — match iff ``tool_name`` plus
      the full ``arguments`` dict equals ``matcher``.
    * ``PERSISTENT_PATTERN`` — match iff ``tool_name`` matches and each
      key in ``matcher`` is present in the request args with a string
      value that matches the pattern glob / prefix.
    * ``ONE_SHOT`` rules are never stored; they exist only as a
      terminal value on a single decision.
    """

    rule_id: str
    tool_name: str
    scope: PermissionScope
    matcher: dict[str, Any]
    allow: bool
    created_at: float = field(default_factory=time)
    note: str | None = None

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "tool_name": self.tool_name,
            "scope": self.scope.value,
            "matcher": self.matcher,
            "allow": self.allow,
            "created_at": self.created_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PermissionRule":
        return cls(
            rule_id=payload["rule_id"],
            tool_name=payload["tool_name"],
            scope=PermissionScope(payload["scope"]),
            matcher=dict(payload.get("matcher", {})),
            allow=bool(payload.get("allow", True)),
            created_at=float(payload.get("created_at", time())),
            note=payload.get("note"),
        )
