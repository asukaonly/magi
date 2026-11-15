"""Shared memory evidence classification and policy models."""

from __future__ import annotations

from magi_plugin_sdk.storage_models.evidence import (
    _LabeledIntEnum as _LabeledIntEnum,
    EvidenceStatus as EvidenceStatus,
    EvidenceClass as EvidenceClass,
    L1RetrievalScope as L1RetrievalScope,
    USER_VISIBLE_L1_RETRIEVAL_SCOPES as USER_VISIBLE_L1_RETRIEVAL_SCOPES,
    GraphScope as GraphScope,
    EVIDENCE_RULE_VERSION as EVIDENCE_RULE_VERSION,
    EvidenceClassification as EvidenceClassification,
    PolicyDecision as PolicyDecision,
    __all__ as __all__,
)

# Version 6 removes the unreachable event-level "report about others" class
# and aligns external observations with their graph-only write capability.
