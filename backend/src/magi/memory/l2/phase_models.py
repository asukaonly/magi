"""Phase extraction and reconciliation contracts for L2 memory.

This module is kept as the compatibility import hub for callers that import
phase contracts from ``magi.memory.l2.phase_models``.
"""

from __future__ import annotations

from .phase1_models import (
    L2ClaimEvidenceMode,
    L2FactKind,
    L2Phase1Entity,
    L2Phase1FactClaim,
    L2Phase1ResolvedRef,
    L2Phase1Result,
)
from .phase2_models import L2Phase2Result, L2Phase2Summary
from .phase_aux_models import (
    ContradictionHint,
    ReconciledTraitOutcome,
    StructuredEntityHint,
    StructuredGraphHint,
)


__all__ = [
    "ContradictionHint",
    "L2ClaimEvidenceMode",
    "L2FactKind",
    "L2Phase1Entity",
    "L2Phase1FactClaim",
    "L2Phase1ResolvedRef",
    "L2Phase1Result",
    "L2Phase2Result",
    "L2Phase2Summary",
    "ReconciledTraitOutcome",
    "StructuredEntityHint",
    "StructuredGraphHint",
]
