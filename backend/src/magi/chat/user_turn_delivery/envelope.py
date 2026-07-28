"""Validation and JSON codec for durable user-turn runtime envelopes."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from ...core.runtime_namespace import DEFAULT_RUNTIME_NAMESPACE
from ..contracts import ChatUserTurnDeliveryRecord


class InvalidUserTurnDeliveryEnvelopeError(ValueError):
    """Raised when a persisted runtime envelope cannot be replayed safely."""


@dataclass(frozen=True, slots=True)
class UserTurnRuntimeEnvelope:
    """Validated replay input stored alongside one accepted user turn."""

    source: str
    user_id: str
    session_id: str
    turn_id: str
    message: str
    attachments: list[dict[str, Any]]
    workspace_path: str | None
    interaction_kind: str | None
    metadata: dict[str, Any]
    runtime_namespace: str


def normalize_runtime_envelope(value: object) -> dict[str, Any]:
    """Copy one JSON-compatible envelope into its durable normalized shape."""

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("Runtime delivery envelope must be an object")
    normalized = deserialize_runtime_envelope(serialize_runtime_envelope(value))
    if not normalized:
        return {}
    return normalized


def serialize_runtime_envelope(value: object) -> str:
    """Serialize one envelope deterministically for request identity checks."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def deserialize_runtime_envelope(value: object) -> dict[str, Any]:
    """Decode one stored envelope, returning an empty object for corrupt JSON."""

    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def runtime_workspace_path(runtime_envelope: dict[str, Any]) -> str | None:
    """Read the accepted workspace path from a normalized delivery envelope."""

    raw_path = runtime_envelope.get("workspace_path")
    if not isinstance(raw_path, str):
        return None
    return raw_path.strip() or None


def parse_user_turn_runtime_envelope(
    record: ChatUserTurnDeliveryRecord,
) -> UserTurnRuntimeEnvelope:
    """Validate the durable runtime envelope against its owning chat row."""

    raw = record.runtime_envelope
    if not isinstance(raw, dict):
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope must be an object"
        )
    user_id = _required_string(raw.get("user_id"), label="user_id")
    session_id = _required_string(raw.get("session_id"), label="session_id")
    turn_id = _required_string(raw.get("turn_id"), label="turn_id")
    if user_id != record.user_id:
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has the wrong user"
        )
    if session_id != record.session_id:
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has the wrong session"
        )
    if turn_id != record.turn_id:
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has the wrong turn"
        )

    message = raw.get("message")
    if not isinstance(message, str):
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has an invalid message"
        )
    raw_attachments = raw.get("attachments")
    if not isinstance(raw_attachments, list) or not all(
        isinstance(item, dict) for item in raw_attachments
    ):
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has invalid attachments"
        )
    if not message.strip() and not raw_attachments:
        raise InvalidUserTurnDeliveryEnvelopeError("Persisted user-turn runtime envelope is empty")
    raw_metadata = raw.get("metadata")
    if not isinstance(raw_metadata, dict):
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has invalid metadata"
        )

    return UserTurnRuntimeEnvelope(
        source=_optional_string(raw.get("source")) or "api",
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id,
        message=message,
        attachments=[dict(item) for item in raw_attachments],
        workspace_path=_optional_string(raw.get("workspace_path")),
        interaction_kind=_optional_string(raw.get("interaction_kind")),
        metadata=dict(raw_metadata),
        runtime_namespace=(
            _optional_string(raw.get("runtime_namespace")) or DEFAULT_RUNTIME_NAMESPACE
        ),
    )


def _required_string(value: object, *, label: str) -> str:
    normalized = _optional_string(value)
    if normalized is None:
        raise InvalidUserTurnDeliveryEnvelopeError(
            f"Persisted user-turn runtime envelope has no {label}"
        )
    return normalized


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidUserTurnDeliveryEnvelopeError(
            "Persisted user-turn runtime envelope has a non-string field"
        )
    return value.strip() or None


__all__ = [
    "InvalidUserTurnDeliveryEnvelopeError",
    "UserTurnRuntimeEnvelope",
    "deserialize_runtime_envelope",
    "normalize_runtime_envelope",
    "parse_user_turn_runtime_envelope",
    "runtime_workspace_path",
    "serialize_runtime_envelope",
]
