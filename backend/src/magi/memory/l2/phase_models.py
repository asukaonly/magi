"""Phase extraction and reconciliation contracts for L2 memory.

This module exposes the supported extraction and reconciliation contracts.
"""

from __future__ import annotations

from .phase1_models import (
    L2AssertionMode,
    L2EntityReferentKind,
    L2ClaimEvidenceMode,
    L2FactKind,
    L2Phase1Entity,
    L2Phase1FactClaim,
    L2Phase1ResolvedRef,
    L2Phase1Result,
)
from .phase_aux_models import (
    ContradictionHint,
    ReconciledTraitOutcome,
    StructuredEntityHint,
    StructuredGraphHint,
)


__all__ = [
    "ContradictionHint",
    "L2AssertionMode",
    "L2EntityReferentKind",
    "L2ClaimEvidenceMode",
    "L2FactKind",
    "L2Phase1Entity",
    "L2Phase1FactClaim",
    "L2Phase1ResolvedRef",
    "L2Phase1Result",
    "ReconciledTraitOutcome",
    "StructuredEntityHint",
    "StructuredGraphHint",
]
