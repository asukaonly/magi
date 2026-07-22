"""Reference-grounded persona research contracts and policy."""

from .models import (
    PersonaExpressionLevel,
    PersonaFidelityLevel,
    PersonaResearchPreference,
    ReferenceDossier,
    ReferenceIdentity,
    ReferenceIdentityVerification,
    ReferenceResearchDecision,
    ReferenceResearchLevel,
    ReferenceResearchPolicyInput,
    ReferenceSource,
)
from .policy import decide_reference_research

__all__ = [
    "PersonaExpressionLevel",
    "PersonaFidelityLevel",
    "PersonaResearchPreference",
    "ReferenceDossier",
    "ReferenceIdentity",
    "ReferenceIdentityVerification",
    "ReferenceResearchDecision",
    "ReferenceResearchLevel",
    "ReferenceResearchPolicyInput",
    "ReferenceSource",
    "decide_reference_research",
]
