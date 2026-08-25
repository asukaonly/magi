"""Provider-neutral model-context records owned by the chat domain."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class ModelContextItemKind(str, Enum):
    """Semantic kinds that can appear on the model-visible context surface."""

    TURN_CONTEXT = "turn_context"
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    ASSISTANT_TOOL_CALL = "assistant_tool_call"
    TOOL_RESULT = "tool_result"
    RUNTIME_CONTROL = "runtime_control"
    RUNTIME_OBSERVATION = "runtime_observation"
    COMPACTION_SUMMARY = "compaction_summary"


class ModelContextScope(str, Enum):
    """Origin boundary for a model-context item, not a retention policy.

    Items remain on the current surface until explicit compaction or governed
    deletion, regardless of the boundary that produced them.
    """

    SESSION = "session"
    TURN = "turn"
    RUN = "run"


@dataclass(frozen=True, slots=True)
class ModelContextItem:
    """One normalized item and its provider-facing message projection."""

    kind: ModelContextItemKind
    message: Mapping[str, Any]
    source: str
    scope: ModelContextScope = ModelContextScope.SESSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        role = str(self.message.get("role") or "").strip()
        if role not in {"user", "assistant", "tool", "tool_result"}:
            raise ValueError(f"Unsupported model-context message role: {role or '<empty>'}")
        if not str(self.source or "").strip():
            raise ValueError("Model-context source is required")

    def to_prompt_message(self) -> dict[str, Any]:
        """Return an isolated provider-facing message dictionary."""

        return deepcopy(dict(self.message))

    def to_payload(self) -> dict[str, Any]:
        """Serialize the stable provider-neutral representation."""

        return {
            "kind": self.kind.value,
            "message": deepcopy(dict(self.message)),
            "source": self.source,
            "scope": self.scope.value,
            "metadata": deepcopy(dict(self.metadata)),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ModelContextItem":
        """Restore one item from durable JSON data."""

        message = payload.get("message")
        metadata = payload.get("metadata")
        if not isinstance(message, Mapping):
            raise ValueError("Model-context payload is missing a message object")
        return cls(
            kind=ModelContextItemKind(str(payload.get("kind") or "")),
            message=dict(message),
            source=str(payload.get("source") or ""),
            scope=ModelContextScope(str(payload.get("scope") or ModelContextScope.SESSION.value)),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )

    @classmethod
    def from_prompt_message(
        cls,
        message: Mapping[str, Any],
        *,
        source: str,
        kind: ModelContextItemKind | None = None,
        scope: ModelContextScope = ModelContextScope.SESSION,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ModelContextItem":
        """Normalize an existing runtime message without provider coupling."""

        resolved_kind = kind or infer_model_context_item_kind(message)
        return cls(
            kind=resolved_kind,
            message=dict(message),
            source=source,
            scope=scope,
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True, slots=True)
class ModelContextEvent:
    """One append-only context-log event."""

    event_id: str
    session_id: str
    generation: int
    sequence_no: int
    operation: str
    item: ModelContextItem
    turn_id: str | None
    run_id: str | None
    step_index: int | None
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class ModelContextSnapshot:
    """Current ordered model-facing surface and its optimistic revision."""

    session_id: str
    generation: int
    revision: int
    events: tuple[ModelContextEvent, ...] = ()

    @property
    def items(self) -> tuple[ModelContextItem, ...]:
        return tuple(event.item for event in self.events)

    def to_prompt_messages(self) -> list[dict[str, Any]]:
        return [event.item.to_prompt_message() for event in self.events]


@dataclass(frozen=True, slots=True)
class ModelContextEpoch:
    """Deduplicated stable system prompt and tool declaration set."""

    epoch_id: str
    session_id: str
    generation: int
    system_prompt: str
    tools: tuple[Mapping[str, Any], ...]
    system_hash: str
    tools_hash: str
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class ModelContextBoundary:
    """One durable model-call boundary over a surface revision and epoch."""

    boundary_id: str
    session_id: str
    generation: int
    boundary_no: int
    surface_revision: int
    epoch_id: str
    boundary_kind: str
    turn_id: str | None
    run_id: str | None
    step_index: int | None
    created_at_ms: int


class ModelContextRevisionConflictError(RuntimeError):
    """Raised when a stale writer tries to replace the current surface."""


def infer_model_context_item_kind(message: Mapping[str, Any]) -> ModelContextItemKind:
    """Infer the semantic kind for ordinary provider-facing messages."""

    role = str(message.get("role") or "").strip()
    if role in {"tool", "tool_result"}:
        return ModelContextItemKind.TOOL_RESULT
    if role == "assistant":
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            return ModelContextItemKind.ASSISTANT_TOOL_CALL
        return ModelContextItemKind.ASSISTANT_MESSAGE
    return ModelContextItemKind.USER_MESSAGE


def build_turn_context_message(content: str) -> dict[str, str] | None:
    """Build the explicit message that freezes one turn's dynamic context."""

    normalized = str(content or "").strip()
    if not normalized:
        return None
    return {
        "role": "user",
        "content": f"<turn_context>\n{normalized}\n</turn_context>",
    }


def is_turn_context_message(message: Mapping[str, Any]) -> bool:
    """Return whether a provider-facing message is a turn-context snapshot."""

    if str(message.get("role") or "").strip() != "user":
        return False
    content = message.get("content")
    if isinstance(content, str):
        return content.lstrip().startswith("<turn_context>")
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "text":
            continue
        return str(block.get("text") or "").lstrip().startswith("<turn_context>")
    return False


__all__ = [
    "ModelContextBoundary",
    "ModelContextEpoch",
    "ModelContextEvent",
    "ModelContextItem",
    "ModelContextItemKind",
    "ModelContextRevisionConflictError",
    "ModelContextScope",
    "ModelContextSnapshot",
    "build_turn_context_message",
    "infer_model_context_item_kind",
    "is_turn_context_message",
]
