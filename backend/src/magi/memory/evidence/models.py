"""Shared memory evidence classification and policy models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


from magi_plugin_sdk.storage_models.evidence import (
    _LabeledIntEnum,
    EvidenceStatus,
    EvidenceClass,
    L1RetrievalScope,
    USER_VISIBLE_L1_RETRIEVAL_SCOPES,
    GraphScope,
    EVIDENCE_RULE_VERSION,
    EvidenceClassification,
    PolicyDecision,
    __all__,
)


# Version 6 removes the unreachable event-level "report about others" class
# and aligns external observations with their graph-only write capability.
