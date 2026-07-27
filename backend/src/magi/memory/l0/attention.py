"""Domain contracts for session-local L0 attention state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Any, Iterable


class AttentionKind(str, Enum):
    """Supported meanings for short-lived attention items."""

    FOCUS = "focus"
    SITUATION = "situation"
    OPEN_LOOP = "open_loop"
    ACTIVE_OBJECT = "active_object"
    CONSTRAINT = "constraint"
    CONSENSUS = "consensus"


class AttentionStatus(str, Enum):
    """Lifecycle states for one attention item."""

    ACTIVE = "active"
    BACKGROUND = "background"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"


class AttentionEvidenceMode(str, Enum):
    """Whether an item is directly stated or cautiously inferred."""

    DIRECT = "direct"
    INFERRED = "inferred"


class AttentionActionType(str, Enum):
    """Patch operations emitted by post-turn understanding."""

    ADD = "add"
    REINFORCE = "reinforce"
    RESOLVE = "resolve"
    SUPERSEDE = "supersede"
    BACKGROUND = "background"


@dataclass(frozen=True, slots=True)
class AttentionUpdateAction:
    """One validated change to a session attention frame."""

    action: AttentionActionType
    target_item_id: str | None = None
    kind: AttentionKind | None = None
    summary: str | None = None
    salience: float = 0.5
    confidence: float = 0.8
    evidence_mode: AttentionEvidenceMode = AttentionEvidenceMode.DIRECT
    source_turn_ids: tuple[str, ...] = ()
    source_event_ids: tuple[str, ...] = ()
    entity_id: str | None = None
    task_id: str | None = None
    task_attempt: int | None = None

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        allowed_turn_ids: Iterable[str] = (),
    ) -> "AttentionUpdateAction | None":
        """Parse an untrusted analyzer payload into a bounded action."""

        try:
            action = AttentionActionType(str(payload.get("action") or "").strip())
        except ValueError:
            return None

        raw_target = str(payload.get("target_item_id") or "").strip()
        raw_summary = " ".join(str(payload.get("summary") or "").split())
        raw_kind = str(payload.get("kind") or "").strip()
        kind: AttentionKind | None = None
        if raw_kind:
            try:
                kind = AttentionKind(raw_kind)
            except ValueError:
                return None

        if action in {AttentionActionType.ADD, AttentionActionType.SUPERSEDE}:
            if kind is None or not raw_summary:
                return None
        if action is not AttentionActionType.ADD and not raw_target:
            return None

        evidence_mode_raw = str(payload.get("evidence_mode") or "direct").strip()
        try:
            evidence_mode = AttentionEvidenceMode(evidence_mode_raw)
        except ValueError:
            evidence_mode = AttentionEvidenceMode.INFERRED

        allowed = {
            str(turn_id).strip()
            for turn_id in allowed_turn_ids
            if str(turn_id).strip()
        }
        raw_source_turn_ids = payload.get("source_turn_ids")
        if not isinstance(raw_source_turn_ids, (list, tuple, set)):
            raw_source_turn_ids = ()
        source_turn_ids = tuple(
            dict.fromkeys(
                turn_id
                for turn_id in (
                    str(value).strip()
                    for value in raw_source_turn_ids
                    if isinstance(value, str)
                )
                if turn_id and (not allowed or turn_id in allowed)
            )
        )[:8]
        raw_source_event_ids = payload.get("source_event_ids")
        if not isinstance(raw_source_event_ids, (list, tuple, set)):
            raw_source_event_ids = ()
        source_event_ids = tuple(
            dict.fromkeys(
                event_id
                for event_id in (
                    str(value).strip()
                    for value in raw_source_event_ids
                    if isinstance(value, str)
                )
                if event_id
            )
        )[:8]

        return cls(
            action=action,
            target_item_id=raw_target or None,
            kind=kind,
            summary=raw_summary[:240] or None,
            salience=_bounded_float(payload.get("salience"), default=0.5),
            confidence=_bounded_float(payload.get("confidence"), default=0.8),
            evidence_mode=evidence_mode,
            source_turn_ids=source_turn_ids,
            source_event_ids=source_event_ids,
            entity_id=str(payload.get("entity_id") or "").strip()[:160] or None,
            task_id=str(payload.get("task_id") or "").strip()[:160] or None,
            task_attempt=_optional_nonnegative_int(payload.get("task_attempt")),
        )


def _bounded_float(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return max(0.0, min(1.0, number))


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


__all__ = [
    "AttentionActionType",
    "AttentionEvidenceMode",
    "AttentionKind",
    "AttentionStatus",
    "AttentionUpdateAction",
]
