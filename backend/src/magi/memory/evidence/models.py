"""Shared memory evidence classification and policy models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class _LabeledIntEnum(IntEnum):
    @property
    def label(self) -> str:
        return type(self)._labels()[self]

    @classmethod
    def from_value(cls, value: "_LabeledIntEnum | int | str") -> "_LabeledIntEnum":
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(value)
        normalized = str(value).strip().lower()
        if normalized.isdigit():
            return cls(int(normalized))
        try:
            return cls._labels_by_name()[normalized]
        except KeyError as exc:
            raise ValueError(f"Unsupported {cls.__name__}: {value}") from exc

    @classmethod
    def _labels(cls) -> dict["_LabeledIntEnum", str]:
        raise NotImplementedError

    @classmethod
    def _labels_by_name(cls) -> dict[str, "_LabeledIntEnum"]:
        return {label: item for item, label in cls._labels().items()}


class EvidenceStatus(_LabeledIntEnum):
    UNKNOWN = 1
    CLASSIFIED = 2
    CLASSIFICATION_ERROR = 3
    POLICY_ERROR = 4

    @classmethod
    def _labels(cls) -> dict["EvidenceStatus", str]:
        return {
            cls.UNKNOWN: "unknown",
            cls.CLASSIFIED: "classified",
            cls.CLASSIFICATION_ERROR: "classification_error",
            cls.POLICY_ERROR: "policy_error",
        }


class EvidenceClass(_LabeledIntEnum):
    UNKNOWN = 1
    USER_SELF_REPORT = 2
    USER_REPORT_ABOUT_OTHERS = 3
    ASSISTANT_QUOTE = 4
    ASSISTANT_TOOL_GROUNDED = 5
    ASSISTANT_FREEFORM = 6
    ASSISTANT_RUNTIME_DERIVATION = 7
    EXTERNAL_OBSERVATION = 8
    SYSTEM_RUNTIME = 9
    USER_QUESTION = 10
    USER_REQUEST = 11

    @classmethod
    def _labels(cls) -> dict["EvidenceClass", str]:
        return {
            cls.UNKNOWN: "unknown",
            cls.USER_SELF_REPORT: "user_self_report",
            cls.USER_REPORT_ABOUT_OTHERS: "user_report_about_others",
            cls.ASSISTANT_QUOTE: "assistant_quote",
            cls.ASSISTANT_TOOL_GROUNDED: "assistant_tool_grounded",
            cls.ASSISTANT_FREEFORM: "assistant_freeform",
            cls.ASSISTANT_RUNTIME_DERIVATION: "assistant_runtime_derivation",
            cls.EXTERNAL_OBSERVATION: "external_observation",
            cls.SYSTEM_RUNTIME: "system_runtime",
            cls.USER_QUESTION: "user_question",
            cls.USER_REQUEST: "user_request",
        }


class L1RetrievalScope(_LabeledIntEnum):
    NONE = 1
    FACT_AUTHORITATIVE = 2
    CONVERSATION_ONLY = 3
    AUDIT_ONLY = 4
    SOURCE_BACKLINK_ONLY = 5

    @classmethod
    def _labels(cls) -> dict["L1RetrievalScope", str]:
        return {
            cls.NONE: "none",
            cls.FACT_AUTHORITATIVE: "fact_authoritative",
            cls.CONVERSATION_ONLY: "conversation_only",
            cls.AUDIT_ONLY: "audit_only",
            cls.SOURCE_BACKLINK_ONLY: "source_backlink_only",
        }


USER_VISIBLE_L1_RETRIEVAL_SCOPES = tuple(
    scope.label for scope in L1RetrievalScope if scope != L1RetrievalScope.AUDIT_ONLY
)


class GraphScope(_LabeledIntEnum):
    NONE = 1
    FULL = 2

    @classmethod
    def _labels(cls) -> dict["GraphScope", str]:
        return {
            cls.NONE: "none",
            cls.FULL: "full",
        }


class AssertionScope(_LabeledIntEnum):
    NONE = 1
    TOPOLOGY_ONLY = 2
    FULL = 3

    @classmethod
    def _labels(cls) -> dict["AssertionScope", str]:
        return {
            cls.NONE: "none",
            cls.TOPOLOGY_ONLY: "topology_only",
            cls.FULL: "full",
        }


# Version 5 recognizes the exact user-authored history-document contract before
# conversational question/request heuristics. The bump reclassifies existing
# imported documents that may otherwise be excluded from L2 projection.
EVIDENCE_RULE_VERSION = 5


@dataclass(slots=True)
class EvidenceClassification:
    """Classification result used by memory evidence governance."""

    evidence_class: str
    reason_code: str
    speaker_role: str | None = None
    grounding_type: str | None = None
    semantic_owner: str | None = None
    originality_type: str | None = None
    source_event_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass(slots=True)
class PolicyDecision:
    """Resolved write and retrieval policy for one classified evidence item."""

    allow_entity_extraction: bool
    allow_graph_write: bool
    allow_assertion_write: bool
    allow_snapshot_impact: bool
    l1_retrieval_scope: str
    graph_scope: str
    assertion_scope: str
    evidence_weight: float
    count_as_new_evidence: bool
    require_source_backlink: bool
    skip_reason: str | None = None


__all__ = [
    "AssertionScope",
    "EVIDENCE_RULE_VERSION",
    "EvidenceClass",
    "EvidenceClassification",
    "EvidenceStatus",
    "GraphScope",
    "L1RetrievalScope",
    "PolicyDecision",
    "USER_VISIBLE_L1_RETRIEVAL_SCOPES",
]
