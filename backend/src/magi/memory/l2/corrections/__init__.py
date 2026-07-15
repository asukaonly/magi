"""Durable user-governed correction primitives for L2 memory."""

from .fingerprints import (
    assertion_claim_fingerprint,
    assertion_slot_key,
    canonical_claim_value,
    canonical_scope_json,
    relationship_claim_fingerprint,
    relationship_slot_key,
    scope_key,
)
from .models import (
    ApplyAssertionCorrectionCommand,
    AssertionCorrectionResult,
    CorrectionCreateResult,
    CorrectionKind,
    CorrectionRule,
    CorrectionRuleKind,
    CorrectionState,
    CorrectionTargetKind,
    MemoryCorrection,
    NewMemoryCorrection,
)
from .repository import MemoryCorrectionRepository
from .service import (
    MemoryCorrectionConflictError,
    MemoryCorrectionService,
    MemoryCorrectionValidationError,
)

__all__ = [
    "ApplyAssertionCorrectionCommand",
    "AssertionCorrectionResult",
    "CorrectionCreateResult",
    "CorrectionKind",
    "CorrectionRule",
    "CorrectionRuleKind",
    "CorrectionState",
    "CorrectionTargetKind",
    "MemoryCorrection",
    "MemoryCorrectionRepository",
    "MemoryCorrectionConflictError",
    "MemoryCorrectionService",
    "MemoryCorrectionValidationError",
    "NewMemoryCorrection",
    "assertion_claim_fingerprint",
    "assertion_slot_key",
    "canonical_claim_value",
    "canonical_scope_json",
    "relationship_claim_fingerprint",
    "relationship_slot_key",
    "scope_key",
]
