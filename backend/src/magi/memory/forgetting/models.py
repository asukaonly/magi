"""Value objects for resumable forget operations."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Literal

from ..source_event_governance import normalize_source_event_ids

SelectorKind = Literal[
    "known_events",
    "entity",
    "time_range",
    "episode",
    "chat_session",
    "chat_history",
    "chat_message",
]
ReferenceRole = Literal["barrier", "cleanup", "target"]
ReferenceType = Literal[
    "exact_event",
    "audit_event",
    "turn",
    "chat_session",
    "source_item",
    "idempotency",
    "chat_projection",
    "entity_refresh",
    "entity_refresh_prepared",
]


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _required_text(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class ForgetSelector:
    """Canonical identity and immutable parameters for one forget request."""

    kind: SelectorKind
    payload: dict[str, Any]

    @classmethod
    def known_events(
        cls,
        event_ids: list[str] | tuple[str, ...],
        *,
        block_source_item: bool,
        include_turn_references: bool = True,
    ) -> "ForgetSelector":
        normalized = tuple(sorted(normalize_source_event_ids(event_ids)))
        if not normalized:
            raise ValueError("event_ids must not be empty")
        return cls(
            kind="known_events",
            payload={
                "event_ids": list(normalized),
                "block_source_item": bool(block_source_item),
                "include_turn_references": bool(include_turn_references),
            },
        )

    @classmethod
    def entity(cls, entity_id: str, *, delete_l1_events: bool) -> "ForgetSelector":
        return cls(
            kind="entity",
            payload={
                "entity_id": _required_text(entity_id, field="entity_id"),
                "delete_l1_events": bool(delete_l1_events),
            },
        )

    @classmethod
    def time_range(
        cls,
        *,
        start: float,
        end: float,
        delete_l1_events: bool,
    ) -> "ForgetSelector":
        range_start = float(start)
        range_end = float(end)
        if not math.isfinite(range_start) or not math.isfinite(range_end):
            raise ValueError("time range must be finite")
        if range_end <= range_start:
            raise ValueError("end must be greater than start")
        return cls(
            kind="time_range",
            payload={
                "start": range_start,
                "end": range_end,
                "delete_l1_events": bool(delete_l1_events),
            },
        )

    @classmethod
    def episode(cls, episode_id: str, *, delete_events: bool) -> "ForgetSelector":
        return cls(
            kind="episode",
            payload={
                "episode_id": _required_text(episode_id, field="episode_id"),
                "delete_events": bool(delete_events),
            },
        )

    @classmethod
    def chat_session(
        cls,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str] | tuple[str, ...],
    ) -> "ForgetSelector":
        return cls(
            kind="chat_session",
            payload={
                "user_id": _required_text(user_id, field="user_id"),
                "session_id": _required_text(session_id, field="session_id"),
                "turn_ids": list(sorted(normalize_source_event_ids(turn_ids))),
            },
        )

    @classmethod
    def chat_message(
        cls,
        *,
        user_id: str,
        session_id: str,
        message_id: str,
        source: str,
        event_type: str,
    ) -> "ForgetSelector":
        return cls(
            kind="chat_message",
            payload={
                "user_id": _required_text(user_id, field="user_id"),
                "session_id": _required_text(session_id, field="session_id"),
                "message_id": _required_text(message_id, field="message_id"),
                "source": _required_text(source, field="source"),
                "event_type": _required_text(event_type, field="event_type"),
            },
        )

    @classmethod
    def chat_history(
        cls,
        *,
        user_id: str,
        session_id: str,
        turn_ids: list[str] | tuple[str, ...],
        messages: list[dict[str, str]] | tuple[dict[str, str], ...],
        surface_message_ids: list[str] | tuple[str, ...],
    ) -> "ForgetSelector":
        """Snapshot the exact chat sources present when history is cleared."""
        normalized_messages: dict[tuple[str, str, str], dict[str, str]] = {}
        for message in messages:
            message_id = _required_text(message.get("message_id"), field="message_id")
            source = _required_text(message.get("source"), field="source")
            event_type = _required_text(message.get("event_type"), field="event_type")
            normalized_messages[(message_id, source, event_type)] = {
                "message_id": message_id,
                "source": source,
                "event_type": event_type,
            }
        return cls(
            kind="chat_history",
            payload={
                "user_id": _required_text(user_id, field="user_id"),
                "session_id": _required_text(session_id, field="session_id"),
                "turn_ids": list(sorted(normalize_source_event_ids(turn_ids))),
                "messages": [normalized_messages[key] for key in sorted(normalized_messages)],
                "surface_message_ids": list(
                    sorted(normalize_source_event_ids(surface_message_ids))
                ),
            },
        )

    @property
    def canonical_json(self) -> str:
        return _canonical_json(self.payload)

    @property
    def selector_hash(self) -> str:
        identity_payload = self.payload
        if self.kind == "chat_session":
            # Turn ids are cleanup material discovered at deletion time. The
            # durable business identity is the session itself, so a retry can
            # still find the completed operation after the chat rows are gone.
            identity_payload = {
                "user_id": self.payload.get("user_id"),
                "session_id": self.payload.get("session_id"),
            }
        encoded = f"{self.kind}\n{_canonical_json(identity_payload)}".encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_json(cls, *, kind: str, selector_json: str) -> "ForgetSelector":
        payload = json.loads(selector_json)
        if not isinstance(payload, dict):
            raise ValueError("Forget selector payload must be an object")
        return cls(kind=kind, payload=payload)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ForgetReference:
    """One typed barrier or cleanup identity owned by an operation item."""

    item_event_id: str
    role: ReferenceRole
    ref_type: ReferenceType
    value: str

    def __post_init__(self) -> None:
        if not str(self.value or "").strip():
            raise ValueError("Forget reference value must not be empty")


@dataclass(frozen=True, slots=True)
class ForgetOperation:
    """Persisted state required to resume one operation."""

    operation_id: str
    selector: ForgetSelector
    reason: str
    status: str
    phase: str
    projection_cursor: str
    projection_selection_complete: bool
    cursor: str
    selection_complete: bool
    selector_cleanup_complete: bool
    total_event_count: int
    active_event_count: int
    cleaned_event_count: int
    attempt_count: int
    lease_token: int
    created_at: float
    surface_finalized_at: float | None
    result: dict[str, Any]
    last_error: str | None

    @property
    def completed(self) -> bool:
        return self.status == "completed"


@dataclass(frozen=True, slots=True)
class ForgetOutcome:
    """Stable result returned for both first execution and idempotent retries."""

    operation_id: str
    selector_kind: SelectorKind
    event_count: int
    target_result: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SelectedEvent:
    """One raw L1 source row and whether it was visible at selection time."""

    event_id: str
    was_active: bool


__all__ = [
    "ForgetOperation",
    "ForgetOutcome",
    "ForgetReference",
    "ForgetSelector",
    "SelectedEvent",
    "ReferenceRole",
    "ReferenceType",
    "SelectorKind",
]
