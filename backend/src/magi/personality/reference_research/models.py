"""Shared models for reference-grounded persona research."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

PersonaFidelityLevel = Literal["traits", "natural", "faithful"]
PersonaExpressionLevel = Literal["low", "balanced", "high_contextual"]
PersonaResearchPreference = Literal["auto", "disabled", "required"]
ReferenceResearchLevel = Literal["none", "identity", "representative", "full"]
ReferenceVolatility = Literal["stable", "evolving", "current", "unknown"]
ReferenceGroundingStatus = Literal[
    "disabled",
    "model_prior",
    "verified",
    "unavailable",
    "insufficient",
]
ReferenceIdentityStatus = Literal["verified", "ambiguous", "unverified"]
ReferenceSourceType = Literal[
    "official",
    "first_party",
    "reputable_secondary",
    "community",
    "search_snippet",
    "user_provided",
]


class ReferenceResearchPolicyInput(BaseModel):
    """Inputs that determine whether and how deeply a reference is researched."""

    source_kind: Literal[
        "original",
        "fictional_reference",
        "public_person_reference",
        "private_person_reference",
    ]
    fidelity_level: PersonaFidelityLevel = "natural"
    research_preference: PersonaResearchPreference = "auto"
    identity_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    identity_ambiguous: bool = False
    identity_verified: bool = False
    reference_modified: bool = False
    profile_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    volatility: ReferenceVolatility = "unknown"
    has_user_reference_urls: bool = False


class ReferenceResearchDecision(BaseModel):
    """Deterministic research decision returned to API and generation flows."""

    level: ReferenceResearchLevel
    requires_network: bool
    identity_verification_required: bool
    blocked_reason: Optional[str] = None
    reason_codes: list[str] = Field(default_factory=list)


class ReferenceIdentity(BaseModel):
    """Canonical identity fields that can be reviewed by the user."""

    source_kind: Literal["fictional_reference", "public_person_reference"]
    name: str = Field(min_length=1, max_length=160)
    work_title: Optional[str] = Field(default=None, max_length=240)
    version: Optional[str] = Field(default=None, max_length=240)
    context: Optional[str] = Field(default=None, max_length=500)


class ReferenceSource(BaseModel):
    """One public source used to verify identity or behavioral evidence."""

    source_id: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field(default="", max_length=500)
    domain: str = Field(default="", max_length=255)
    source_type: ReferenceSourceType = "search_snippet"
    authority: float = Field(default=0.5, ge=0.0, le=1.0)
    directness: float = Field(default=0.5, ge=0.0, le=1.0)
    summary: str = Field(default="", max_length=1200)
    retrieved_at: str = Field(default="", max_length=80)
    user_provided: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=8)


class ReferenceEvidenceItem(BaseModel):
    """A bounded behavioral claim with explicit provenance."""

    dimension: Literal[
        "identity",
        "ordinary_baseline",
        "judgment_patterns",
        "speech_rhythm",
        "interaction_patterns",
        "signature_markers",
        "contrast_contexts",
        "version_notes",
    ]
    claim: str = Field(min_length=1, max_length=1000)
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ReferenceDossier(BaseModel):
    """Traceable reference material used by persona generation."""

    schema_version: int = 1
    reference_fingerprint: str = Field(min_length=1, max_length=160)
    identity_status: ReferenceIdentityStatus
    grounding_status: ReferenceGroundingStatus
    research_level: ReferenceResearchLevel
    canonical_identity: Optional[ReferenceIdentity] = None
    profile_dimensions: dict[str, list[str]] = Field(default_factory=dict)
    evidence: list[ReferenceEvidenceItem] = Field(default_factory=list, max_length=48)
    unknowns: list[str] = Field(default_factory=list, max_length=16)
    contradictions: list[str] = Field(default_factory=list, max_length=12)
    sources: list[ReferenceSource] = Field(default_factory=list, max_length=12)
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    volatility: ReferenceVolatility = "unknown"
    sufficient: bool = False
    warning: Optional[str] = Field(default=None, max_length=500)


class ReferenceIdentityVerification(BaseModel):
    """Reviewable identity verification result returned before generation."""

    status: ReferenceIdentityStatus
    canonical_identity: Optional[ReferenceIdentity] = None
    alternatives: list[ReferenceIdentity] = Field(default_factory=list, max_length=4)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_confirmation: bool = True
    reference_fingerprint: Optional[str] = Field(default=None, max_length=160)
    sources: list[ReferenceSource] = Field(default_factory=list, max_length=8)
    warning: Optional[str] = Field(default=None, max_length=500)
