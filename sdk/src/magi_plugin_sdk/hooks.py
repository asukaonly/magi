"""Pure hook event and decision values shared by plugins and the host.

Handlers exchange validated JSON values. Runtime services, credentials, callables,
and other host objects are not part of a hook payload.
"""

from __future__ import annotations

from dataclasses import field

from pydantic import ConfigDict, JsonValue
from pydantic.dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Mapping, Optional


class HookEventType(str, Enum):
    """Events that the model / runtime can fire into the gateway."""

    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PRE_SKILL_USE = "PreSkillUse"
    POST_SKILL_USE = "PostSkillUse"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    SESSION_START = "SessionStart"
    STOP = "Stop"
    SUBAGENT_STOP = "SubagentStop"
    PRE_COMPACT = "PreCompact"
    NOTIFICATION = "Notification"


class HookOutcome(str, Enum):
    CONTINUE = "continue"
    DENY = "deny"
    MODIFY = "modify"
    INJECT_CONTEXT = "inject_context"


@dataclass(frozen=True, config=ConfigDict(extra="forbid", allow_inf_nan=False))
class HookContext:
    """Payload handed to every hook handler.

    Field semantics are union-style: ``tool_name`` / ``arguments`` only
    populate for tool events; ``skill_name`` only for skill events;
    ``user_message`` only for ``USER_PROMPT_SUBMIT``.
    """

    event_type: HookEventType
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    user_id: Optional[str] = None
    workspace: Optional[str] = None
    tool_name: Optional[str] = None
    arguments: Optional[dict[str, JsonValue]] = None
    skill_name: Optional[str] = None
    user_message: Optional[str] = None
    matcher_key: Optional[str] = None  # used by settings.json matcher patterns
    extra: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, config=ConfigDict(extra="forbid", allow_inf_nan=False))
class HookDecision:
    outcome: HookOutcome
    reason: Optional[str] = None
    modified_arguments: Optional[dict[str, JsonValue]] = None
    modified_user_message: Optional[str] = None
    additional_context: Optional[str] = None
    source: Optional[str] = None  # human-readable origin: "settings.json", "plugin:foo", "test"

    @classmethod
    def cont(cls, *, source: Optional[str] = None) -> "HookDecision":
        return cls(outcome=HookOutcome.CONTINUE, source=source)

    @classmethod
    def deny(cls, reason: str, *, source: Optional[str] = None) -> "HookDecision":
        return cls(outcome=HookOutcome.DENY, reason=reason, source=source)

    @classmethod
    def modify(
        cls,
        *,
        arguments: Optional[Mapping[str, JsonValue]] = None,
        user_message: Optional[str] = None,
        source: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> "HookDecision":
        return cls(
            outcome=HookOutcome.MODIFY,
            modified_arguments=dict(arguments) if arguments is not None else None,
            modified_user_message=user_message,
            source=source,
            reason=reason,
        )

    @classmethod
    def inject(cls, context: str, *, source: Optional[str] = None) -> "HookDecision":
        return cls(
            outcome=HookOutcome.INJECT_CONTEXT,
            additional_context=context,
            source=source,
        )


HookHandler = Callable[[HookContext], Awaitable[HookDecision]]


__all__ = [
    "HookContext",
    "HookDecision",
    "HookEventType",
    "HookHandler",
    "HookOutcome",
]
