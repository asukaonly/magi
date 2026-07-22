"""Pydantic schemas for the personality configuration API."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from ...config.models import LLMSettings
from ...personality.reference_research import (
    PersonaExpressionLevel,
    PersonaFidelityLevel,
    PersonaResearchPreference,
    ReferenceIdentityVerification,
)


SUPPORTED_LAYER_MODIFIER_KEYS = (
    "behavior_shifts",
    "memory_behavior",
    "protective_bias",
    "voice_unlocks",
    "humor_delta",
    "directness_delta",
    "register_unlocks",
    "trigger_threshold_shifts",
    "sarcasm_bounds",
)


def _normalize_optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_optional_text_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        items = [line.strip() for line in value.splitlines() if line.strip()]
        return items or None
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or None
    return None


def _normalize_optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_optional_float_mapping(value: Any) -> Optional[Dict[str, float]]:
    if not isinstance(value, dict):
        return None
    result: Dict[str, float] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        number = _normalize_optional_float(raw_value)
        if key and number is not None:
            result[key] = number
    return result or None


class IdentityCoreModel(BaseModel):
    identity_statement: str = Field(default="")
    values_loved: List[str] = Field(default_factory=list)
    values_rejected: List[str] = Field(default_factory=list)
    attention_biases: List[str] = Field(default_factory=list)


class IdiolectModel(BaseModel):
    sentence_style: str = Field(default="")
    vocab_available: List[str] = Field(default_factory=list)
    vocab_avoided: List[str] = Field(default_factory=list)
    structural_quirks: List[str] = Field(default_factory=list)
    chattiness: float = Field(default=0.5, ge=0.0, le=1.0)


class RegisterModel(BaseModel):
    description: str = Field(default="")
    behavior: str = Field(default="")
    examples: List[str] = Field(default_factory=list)


class SignatureTriggerModel(BaseModel):
    trigger_id: str = Field(default="")
    activates_when: str = Field(default="")
    behavior_shift: str = Field(default="")
    intensity_levels: Dict[str, str] = Field(default_factory=dict)
    exit_behavior: str = Field(default="")


class QuietHourModel(BaseModel):
    condition: str = Field(default="")
    clamps: Dict[str, Any] = Field(default_factory=dict)


class LayerModifiersModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    behavior_shifts: Optional[List[str]] = Field(default=None)
    memory_behavior: Optional[str] = Field(default=None)
    protective_bias: Optional[str] = Field(default=None)
    voice_unlocks: Optional[List[str]] = Field(default=None)
    humor_delta: Optional[float] = Field(default=None)
    directness_delta: Optional[float] = Field(default=None)
    register_unlocks: Optional[List[str]] = Field(default=None)
    trigger_threshold_shifts: Optional[Dict[str, float]] = Field(default=None)
    sarcasm_bounds: Optional[str] = Field(default=None)

    @field_validator("behavior_shifts", "voice_unlocks", "register_unlocks", mode="before")
    @classmethod
    def _validate_text_lists(cls, value: Any) -> Optional[List[str]]:
        return _normalize_optional_text_list(value)

    @field_validator("memory_behavior", "protective_bias", "sarcasm_bounds", mode="before")
    @classmethod
    def _validate_text_fields(cls, value: Any) -> Optional[str]:
        return _normalize_optional_text(value)

    @field_validator("humor_delta", "directness_delta", mode="before")
    @classmethod
    def _validate_float_fields(cls, value: Any) -> Optional[float]:
        return _normalize_optional_float(value)

    @field_validator("trigger_threshold_shifts", mode="before")
    @classmethod
    def _validate_float_mapping(cls, value: Any) -> Optional[Dict[str, float]]:
        return _normalize_optional_float_mapping(value)

    @model_serializer(mode="plain")
    def _serialize(self) -> Dict[str, Any]:
        payload = {
            "behavior_shifts": self.behavior_shifts,
            "memory_behavior": self.memory_behavior,
            "protective_bias": self.protective_bias,
            "voice_unlocks": self.voice_unlocks,
            "humor_delta": self.humor_delta,
            "directness_delta": self.directness_delta,
            "register_unlocks": self.register_unlocks,
            "trigger_threshold_shifts": self.trigger_threshold_shifts,
            "sarcasm_bounds": self.sarcasm_bounds,
        }
        return {key: value for key, value in payload.items() if value is not None}


class PersonaLayerModel(BaseModel):
    layer_id: str = Field(default="")
    unlock_condition: Optional[Dict[str, Any]] = Field(default=None)
    modifiers: LayerModifiersModel = Field(default_factory=LayerModifiersModel)


class BootstrapConfigModel(BaseModel):
    style_instruction: str = Field(default="")
    opening_line: str = Field(default="")
    max_rounds: int = Field(default=3)
    opening_examples: List[str] = Field(default_factory=list)


class PersonalityConfigModel(BaseModel):
    name: str = Field(default="AI Assistant")
    avatar: str = Field(default="")
    description: str = Field(default="")
    appearance_prompt: str = Field(default="")
    identity_core: IdentityCoreModel = Field(default_factory=IdentityCoreModel)
    idiolect: IdiolectModel = Field(default_factory=IdiolectModel)
    registers: Dict[str, RegisterModel] = Field(default_factory=dict)
    quiet_hours: List[QuietHourModel] = Field(default_factory=list)
    signature_triggers: List[SignatureTriggerModel] = Field(default_factory=list)
    persona_layers: List[PersonaLayerModel] = Field(default_factory=list)
    dynamic_state_rules: Dict[str, str] = Field(default_factory=dict)
    milestone_conditions: Dict[str, str] = Field(default_factory=dict)
    interim_lines: Dict[str, List[str]] = Field(default_factory=dict)
    bootstrap: Optional[BootstrapConfigModel] = Field(default=None)


PersonaReferenceKind = Literal[
    "fictional_reference",
    "public_person_reference",
    "private_person_reference",
]
PersonaResolutionStatus = Literal["original", "resolved", "ambiguous", "unknown"]
class PersonaReferenceCandidateModel(BaseModel):
    candidate_id: str = Field(default="")
    source_kind: PersonaReferenceKind
    name: str = Field(min_length=1, max_length=160)
    work_title: Optional[str] = Field(default=None, max_length=240)
    version: Optional[str] = Field(default=None, max_length=240)
    context: Optional[str] = Field(default=None, max_length=500)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PersonaIntentResolutionModel(BaseModel):
    status: PersonaResolutionStatus
    candidates: List[PersonaReferenceCandidateModel] = Field(default_factory=list, max_length=4)
    selected_candidate_id: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_confirmation: bool = False
    explicit_constraints: List[str] = Field(default_factory=list)


class PersonaReferenceModel(BaseModel):
    source_kind: PersonaReferenceKind
    name: str = Field(min_length=1, max_length=160)
    work_title: Optional[str] = Field(default=None, max_length=240)
    version: Optional[str] = Field(default=None, max_length=240)
    context: Optional[str] = Field(default=None, max_length=1000)
    user_confirmed: bool = True


class PersonaResearchOptionsModel(BaseModel):
    preference: PersonaResearchPreference = "auto"
    force_refresh: bool = False
    reference_urls: List[str] = Field(default_factory=list, max_length=4)
    identity_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    identity_ambiguous: bool = False
    identity_verified: bool = False
    reference_modified: bool = False
    verification_fingerprint: Optional[str] = Field(default=None, max_length=160)

    @field_validator("reference_urls")
    @classmethod
    def _validate_reference_urls(cls, values: List[str]) -> List[str]:
        normalized: List[str] = []
        for value in values:
            url = str(value).strip()
            if not url.startswith(("https://", "http://")):
                raise ValueError("reference_urls must use http or https")
            if len(url) > 2000:
                raise ValueError("reference_urls cannot exceed 2000 characters")
            if url not in normalized:
                normalized.append(url)
        return normalized


class PersonaGenerationIntentModel(BaseModel):
    source_kind: Literal[
        "original",
        "fictional_reference",
        "public_person_reference",
        "private_person_reference",
    ]
    reference: Optional[PersonaReferenceModel] = None
    fidelity_level: PersonaFidelityLevel
    expression_level: PersonaExpressionLevel
    research: PersonaResearchOptionsModel
    explicit_constraints: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_source_and_research(self) -> "PersonaGenerationIntentModel":
        if self.source_kind == "original":
            if self.reference is not None:
                raise ValueError("original personas cannot include a reference")
            if (
                self.research.preference != "disabled"
                or self.research.reference_urls
                or self.research.force_refresh
            ):
                raise ValueError("original personas cannot use reference research")
            return self
        if self.reference is None:
            raise ValueError("referenced personas require a confirmed reference")
        if self.reference.source_kind != self.source_kind:
            raise ValueError("reference source_kind must match intent source_kind")
        if not self.reference.user_confirmed:
            raise ValueError("referenced personas require user confirmation")
        if self.source_kind == "private_person_reference":
            if self.fidelity_level != "traits":
                raise ValueError("private-person references support traits fidelity only")
            if (
                self.research.preference != "disabled"
                or self.research.reference_urls
                or self.research.force_refresh
            ):
                raise ValueError("private-person references cannot use web research")
        return self


class PersonaIntentResolveRequest(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    target_language: str = Field(default="English")
    llm_override: Optional[LLMSettings] = Field(None, description="Optional unsaved LLM configuration override")


class PersonaIntentResolutionResponse(BaseModel):
    success: bool
    message: str
    data: PersonaIntentResolutionModel


class PersonaIdentityVerifyRequest(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    reference: PersonaReferenceModel
    target_language: str = Field(default="English")
    reference_urls: List[str] = Field(default_factory=list, max_length=4)
    llm_override: Optional[LLMSettings] = Field(None, description="Optional unsaved LLM configuration override")

    @model_validator(mode="after")
    def _validate_public_reference(self) -> "PersonaIdentityVerifyRequest":
        if self.reference.source_kind == "private_person_reference":
            raise ValueError("private-person references cannot use identity verification")
        validated = PersonaResearchOptionsModel(reference_urls=self.reference_urls)
        self.reference_urls = validated.reference_urls
        return self


class PersonaIdentityVerifyResponse(BaseModel):
    success: bool
    message: str
    data: ReferenceIdentityVerification


class AIGenerateRequest(BaseModel):
    description: str = Field(..., description="One-sentence description of AI personality")
    target_language: str = Field(default="English", description="Concrete target language, such as Chinese, English, or Japanese")
    current_config: Optional[PersonalityConfigModel] = Field(None, description="Current configuration (optional)")
    llm_override: Optional[LLMSettings] = Field(None, description="Optional unsaved LLM configuration override")
    draft_id: Optional[str] = Field(default=None, description="Stable client draft identifier")
    request_id: Optional[str] = Field(default=None, description="Idempotency key for starting a generation job")
    intent: Optional[PersonaGenerationIntentModel] = Field(
        default=None,
        description="User-confirmed generation intent from the lightweight resolver",
    )


class PersonaAdjustmentRequest(BaseModel):
    current_config: PersonalityConfigModel
    instruction: str = Field(min_length=1, max_length=2000)
    scope: Literal["auto", "voice", "expression", "behavior"] = "auto"
    target_language: str = Field(default="English")
    intent: Optional[PersonaGenerationIntentModel] = None
    llm_override: Optional[LLMSettings] = Field(None, description="Optional unsaved LLM configuration override")


class PersonalityResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    stages: Optional[List[Dict[str, Any]]] = None
    reference_dossier: Optional[Dict[str, Any]] = None


class BootstrapInitRequest(BaseModel):
    session_id: str = Field(..., description="Chat session to inject the opening into")
    user_id: str = Field(default="default_user")


class JournalReflectRequest(BaseModel):
    persona_name: Optional[str] = Field(None, description="Persona to reflect as; defaults to current")
    emotional_state: Optional[Dict[str, Any]] = None
    relationship: Optional[Dict[str, Any]] = None
    recent_milestones: Optional[List[Dict[str, Any]]] = None


class PersonalityDiff(BaseModel):
    field: str = Field(..., description="Field path")
    field_label: str = Field(..., description="Field display label")
    old_value: Any = Field(None, description="Old value")
    new_value: Any = Field(None, description="New value")


class PersonalityCompareResponse(BaseModel):
    success: bool
    message: str
    from_personality: str
    to_personality: str
    diffs: List[PersonalityDiff]
    from_config: Optional[PersonalityConfigModel] = None
    to_config: Optional[PersonalityConfigModel] = None
