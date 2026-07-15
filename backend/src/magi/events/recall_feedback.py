"""Typed recall-feedback contract carried by user-message events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


RECALL_FEEDBACK_INTERACTION_KIND = "recall_feedback"


class RecallFeedbackKind(str, Enum):
    """Supported answer-level recall correction intents."""

    ANSWER_EVIDENCE_MISMATCH = "answer_evidence_mismatch"
    ITEM_IRRELEVANT = "item_irrelevant"


@dataclass(frozen=True, slots=True)
class RecallFeedbackRequest:
    """One-turn request to re-evaluate a prior memory-grounded answer."""

    kind: RecallFeedbackKind
    target_message_id: str
    finding_ref: str | None = None

    @classmethod
    def from_value(cls, value: object) -> "RecallFeedbackRequest | None":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            return None
        try:
            kind = RecallFeedbackKind(str(value.get("kind") or "").strip())
        except ValueError:
            return None
        target_message_id = str(value.get("target_message_id") or "").strip()
        finding_ref = str(value.get("finding_ref") or "").strip() or None
        if not target_message_id:
            return None
        if kind == RecallFeedbackKind.ITEM_IRRELEVANT and not finding_ref:
            return None
        if kind == RecallFeedbackKind.ANSWER_EVIDENCE_MISMATCH:
            finding_ref = None
        return cls(
            kind=kind,
            target_message_id=target_message_id,
            finding_ref=finding_ref,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind.value,
            "target_message_id": self.target_message_id,
        }
        if self.finding_ref is not None:
            payload["finding_ref"] = self.finding_ref
        return payload


__all__ = [
    "RECALL_FEEDBACK_INTERACTION_KIND",
    "RecallFeedbackKind",
    "RecallFeedbackRequest",
]
