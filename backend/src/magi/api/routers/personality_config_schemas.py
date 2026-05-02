"""Pydantic schemas for the personality configuration API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ...config.models import LLMSettings


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


class PersonaLayerModel(BaseModel):
    layer_id: str = Field(default="")
    unlock_condition: Optional[Dict[str, Any]] = Field(default=None)
    modifiers: Dict[str, Any] = Field(default_factory=dict)


class BootstrapConfigModel(BaseModel):
    style_instruction: str = Field(default="")
    opening_line: str = Field(default="")
    max_rounds: int = Field(default=3)


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


class AIGenerateRequest(BaseModel):
    description: str = Field(..., description="One-sentence description of AI personality")
    target_language: str = Field(default="Auto", description="Target language: Auto/Chinese/English etc.")
    current_config: Optional[PersonalityConfigModel] = Field(None, description="Current configuration (optional)")
    llm_override: Optional[LLMSettings] = Field(None, description="Optional unsaved LLM configuration override")


class PersonalityResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


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
